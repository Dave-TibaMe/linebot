import os
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

# 讀取環境變數
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# 從 .env 環境變數中取得 token / secret
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

GROUP_A = os.getenv("GROUP_ID_A_LEESISTERS")
GROUP_B = os.getenv("GROUP_ID_B_ELSA_ANNA")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.warning("Invalid signature.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    
    if event.source.type != "group" or event.source.group_id != GROUP_A:
        return  # 只處理來自群組 A 的訊息


    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        #line_bot_api.reply_message_with_http_info(
        #    ReplyMessageRequest(
        #        reply_token=event.reply_token,
        #        messages=[TextMessage(text=f'群組ID：{event.source.group_id}')]
        #    )
        #)

        
        # 加上來源標籤的文字訊息
        if isinstance(event.message, TextMessageContent):
            tagged = f"[來自 A 群組] {event.message.text}"
            line_bot_api.push_message(to=GROUP_B, messages=[TextMessage(text=tagged)])

        # 圖片轉發
        elif isinstance(event.message, ImageMessageContent):
            resp = line_bot_api.get_message_content(message_id=event.message.id)
            image_data = resp.read()
            img_msg = ImageMessage(
                original_content_url=None,
                preview_image_url=None,
                content=BytesIO(image_data)
            )
            line_bot_api.push_message(to=GROUP_B, messages=[img_msg, TextMessage(text="[來自 A 群組 – 圖片]")])

        # 影片轉發
        elif isinstance(event.message, VideoMessageContent):
            resp = line_bot_api.get_message_content(message_id=event.message.id)
            video_data = resp.read()
            vid_msg = VideoMessage(
                original_content_url=None,
                preview_image_url=None,
                content=BytesIO(video_data)
            )
            line_bot_api.push_message(to=GROUP_B, messages=[vid_msg, TextMessage(text="[來自 A 群組 – 影片]")])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render 用 PORT，預設 5000
    app.run(host="0.0.0.0", port=port)