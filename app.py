import os
import requests

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    TextMessage,
    ImageMessage,
    VideoMessage,
    PushMessageRequest
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
    VideoMessageContent
)

# 讀取環境變數
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# 從 .env 環境變數中取得 token / secret
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")
IMGUR_UPLOAD_URL = "https://api.imgur.com/3/image"

#GROUP_A = os.getenv("GROUP_ID_A_LEESISTERS")
#GROUP_B = os.getenv("GROUP_ID_B_ELSA_ANNA")
GROUP_A = 'C7688c1f2bc678001d3c49d77aef1e888' #Davis & Zoe - Education
GROUP_B = 'C588382cd48e689885e3f9fc5feae4f90' #Davis & Zoe - 家庭教育

#GROUP_B = 'C8165f7f0ac4ddd169e8ae1dbba6fd2d8' #奕涵詠涵生活大小事
GROUP_A_NAME = os.getenv("GROUP_A_NAME")

def upload_to_imgur(img_bytes):
    headers = {"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"}
    files = {"image": img_bytes}
    resp = requests.post(IMGUR_UPLOAD_URL, headers=headers, files=files)
    data = resp.json()
    try:
        return data["data"]["link"] if data.get("success") else None
    except KeyError as e:
        print(f"錯誤：{e}")
        # 進一步處理錯誤，例如檢查 API 回應的狀態碼
        if "status" in data and data["status"] != 200:
            print(f"狀態碼錯誤：{data['status']}")
        return None
    


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


@handler.add(MessageEvent)
def handle_message(event):

    if event.source.type != "group" or event.source.group_id != GROUP_A:
        return

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)

        text = f'isinstance(event.message, ImageMessageContent):{isinstance(event.message, ImageMessageContent)}'
        api.push_message_with_http_info(
            PushMessageRequest(
                to=GROUP_B,
                messages=[TextMessage(text=text)]
            )
        )
"""
        if isinstance(event.message, TextMessageContent):
            text = event.source.group_id #f"[{GROUP_A_NAME}] {event.message.text}"
            api.push_message_with_http_info(
                PushMessageRequest(
                    to=GROUP_B,
                    messages=[TextMessage(text=text)]
                )
            )
                
        elif isinstance(event.message, ImageMessageContent):
            # 下載圖片內容
            image_url = f"https://api-data.line.me/v2/bot/message/{event.message.id}/content"
            headers = {
                "Authorization": f"Bearer {os.getenv('LINE_CHANNEL_ACCESS_TOKEN')}",
                "Content-Type": "application/octet-stream"
            }
            response = requests.get(image_url, headers=headers)
            if response.status_code == 200:
                content = response.content
                # 將內容上傳到 Imgur
                url = upload_to_imgur(content)
                if url:
                    image_msg = ImageMessage(
                        original_content_url=url,
                        preview_image_url=url
                    )
                    api.push_message_with_http_info(
                        PushMessageRequest(
                            to=GROUP_B,
                            messages=[image_msg, TextMessage(text=f"[{GROUP_A_NAME}]")]
                        )
                    )

        elif isinstance(event.message, VideoMessageContent):
            video_url = f"https://api-data.line.me/v2/bot/message/{event.message.id}/content"
            headers = {
                "Authorization": f"Bearer {os.getenv('LINE_CHANNEL_ACCESS_TOKEN')}"
            }
            response = requests.get(video_url, headers=headers)
            if response.status_code == 200:
                content = response.content
                # 上傳到 Imgur（需確認 Imgur 是否支援影片上傳）
                url = upload_to_imgur(content)
                if url:
                    video_msg = VideoMessage(
                        original_content_url=url,
                        preview_image_url=url
                    )
                    api.push_message_with_http_info(
                        PushMessageRequest(
                            to=GROUP_B,
                            messages=[video_msg, TextMessage(text=f"[{GROUP_A_NAME}]")]
                        )
                    )

"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render 用 PORT，預設 5000
    app.run(host="0.0.0.0", port=port)