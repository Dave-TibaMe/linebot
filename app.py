
import os
import requests # requests 模組在目前版本中並未直接使用於核心轉發邏輯 (除了被註解的 Imgur)
import time   # time 模組在目前版本中並未直接使用 (除了被註解的 Imgur)
import logging
import uuid
import mimetypes
from flask import Flask, request, abort, send_from_directory

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError  # 用於 Webhook 簽名驗證
from linebot.v3.messaging.exceptions import ApiException # 用於 Messaging API 呼叫錯誤
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

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

GROUP_A = os.getenv("GROUP_ID_A_LEESISTERS", 'C7688c1f2bc678001d3c49d77aef1e888')
GROUP_B_ID = os.getenv("GROUP_ID_B_ELSA_ANNA", 'C588382cd48e689885e3f9fc5feae4f90')
GROUP_A_NAME = os.getenv("GROUP_A_NAME", "LeeSisters")

# <<< 修改：修正 DEFAULT_VIDEO_PREVIEW_IMAGE_URL 的設定方式和預設值 >>>
DEFAULT_VIDEO_PREVIEW_IMAGE_URL = os.getenv(
    "DEFAULT_VIDEO_PREVIEW_IMAGE_URL",
    "https://via.placeholder.com/800x800.png?text=VideoPreview" # 使用一個有效的佔位預覽圖 URL
)

TEMP_IMAGE_DIR_NAME = "line_temp_images"
TEMP_IMAGE_DIR_PATH = os.path.join(os.path.dirname(__file__), TEMP_IMAGE_DIR_NAME)
if not os.path.exists(TEMP_IMAGE_DIR_PATH):
    try:
        os.makedirs(TEMP_IMAGE_DIR_PATH)
        logging.info(f"已建立臨時圖片資料夾: {TEMP_IMAGE_DIR_PATH}")
    except OSError as e:
        logging.error(f"建立臨時圖片資料夾失敗: {e}")

APP_BASE_URL = os.getenv("APP_BASE_URL")
if not APP_BASE_URL:
    logging.warning("環境變數 APP_BASE_URL 未設定。圖片轉發功能可能無法正常運作，因為無法產生公開的圖片 URL。")


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    logging.info(f"接收到請求: {body[:300]}...")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("無效的簽名。請檢查您的 Channel Secret。")
        abort(400, "Invalid signature")
    except Exception as e:
        logging.error(f"處理回呼時發生錯誤: {e}", exc_info=True)
        abort(500, "Internal server error")
    return 'OK'

@app.route(f'/{TEMP_IMAGE_DIR_NAME}/<filename>')
def serve_temp_image(filename):
    try:
        return send_from_directory(TEMP_IMAGE_DIR_PATH, filename)
    except FileNotFoundError:
        abort(404)
    except Exception as e:
        logging.error(f"提供臨時圖片 {filename} 時發生錯誤: {e}")
        abort(500)

@handler.add(MessageEvent)
def handle_message(event):
    logging.info(f"處理訊息事件: {event}")

    if event.source.type != "group" or event.source.group_id != GROUP_A:
        logging.info(f"訊息來源非目標群組 {GROUP_A}，忽略。來源: {event.source}")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        group_a_display_name = f"[{GROUP_A_NAME}]" if GROUP_A_NAME else ""

 

        if isinstance(event.message, TextMessageContent):
            text_to_send = f"{group_a_display_name} {event.message.text}".strip()
            logging.info(f"轉發文字訊息至 {GROUP_B_ID}: {text_to_send}")
            line_bot_api.push_message_with_http_info(
                PushMessageRequest(
                    to=GROUP_B_ID,
                    messages=[TextMessage(text=text_to_send)]
                )
            )
                
        elif isinstance(event.message, ImageMessageContent):
            message_id = event.message.id
            logging.info(f"接收到圖片訊息，ID: {message_id}")
            
            if not APP_BASE_URL:
                logging.error("APP_BASE_URL 未設定，無法處理圖片轉發。")
                try: # 嘗試通知來源群組
                    line_bot_api.push_message_with_http_info(
                        PushMessageRequest(
                            to=event.source.group_id,
                            messages=[TextMessage(text="[系統通知] 圖片轉發功能因伺服器設定問題暫停。")]
                        )
                    )
                except Exception as notify_err:
                    logging.error(f"發送 APP_BASE_URL 未設定通知失敗: {notify_err}")
                return

            filepath = None # 初始化檔案路徑變數，用於 finally 中的刪除
            
            try:
                # --- 使用 MessagingApi 的 get_message_content 方法 ---
                # 這個方法返回一個 file-like object (bytes stream)
                message_content_stream = line_bot_api.get_message_content(message_id=message_id) # 或者 api.get_message_content(...)
    
                file_name = f"{message_id}.jpg" # 假設是 jpg
                file_path = os.path.join(TEMP_IMAGE_DIR_NAME, file_name)
    
                with open(file_path, 'wb') as fd:
                    for chunk in message_content_stream: # 迭代讀取 stream 中的數據塊
                        fd.write(chunk)
                # 或者，如果內容不大，可以一次性讀取 (但不推薦用於大檔案)
                # content_bytes = message_content_stream.read()
                # with open(file_path, 'wb') as fd:
                #     fd.write(content_bytes)
    
                logging.info(f"圖片已儲存: {file_path}")
    
                # ... 接下來您可以處理儲存下來的圖片 file_path ...
    
            except ApiException as e: # 捕獲來自 MessagingApi 的錯誤
                logging.error(f"獲取圖片內容時發生 LINE API 錯誤: status={e.status}, reason={e.reason}, body={e.body}")
                # 根據需要處理錯誤，例如回覆錯誤訊息給用戶
            except Exception as e:
                logging.error(f"處理圖片訊息 {message_id} 時發生未預期錯誤: {e}", exc_info=True)
                # 根據需要處理錯誤

        elif isinstance(event.message, VideoMessageContent):
            message_id = event.message.id
            logging.info(f"接收到影片訊息，ID: {message_id}。")
            
            # <<< 修改：釐清影片處理 >>>
            # 目前 upload_to_imgur 函數未定義，因此無法透過 Imgur 上傳影片。
            # 如果要實現影片轉發，需要 original_content_url (實際影片檔案的 URL)
            # 和 preview_image_url (預覽圖的 URL)。
            
            # 範例：如果決定不轉發影片，只記錄
            logging.info(f"影片訊息 {message_id} 已收到，但目前未設定影片轉發處理。")
            
            # 如果未來要實現本地影片轉發，其邏輯會類似圖片轉發，但更複雜。
            # 以下為一個概念性的提示，說明如果要有 original_content_url 和 preview_image_url 才能發送
            # original_video_url = None # 需要實現獲取或生成此 URL 的邏輯
            # preview_video_url = DEFAULT_VIDEO_PREVIEW_IMAGE_URL # 可以使用預設預覽圖

            # if original_video_url and preview_video_url:
            #     logging.info(f"準備轉發影片。Original: {original_video_url}, Preview: {preview_video_url}")
            #     video_msg = VideoMessage(
            #         original_content_url=original_video_url,
            #         preview_image_url=preview_video_url
            #     )
            #     text_label = TextMessage(text=group_a_display_name) if group_a_display_name else None
            #     messages_to_send = [video_msg]
            #     if text_label: messages_to_send.append(text_label)
                
            #     api.push_message_with_http_info(
            #         PushMessageRequest(to=GROUP_B, messages=messages_to_send)
            #     )
            # else:
            #     logging.warning(f"無法獲取影片 {message_id} 的 original_content_url，無法轉發。")
            #     # 修正 logging.error 缺少訊息的問題
            #     # logging.error("影片上傳或處理失敗，無法轉發。") # 如果有嘗試上傳的邏輯

# <<< 移除末尾被註解掉的舊程式碼 >>>

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"應用程式啟動於埠 {port}")
    app.run(host="0.0.0.0", port=port)
