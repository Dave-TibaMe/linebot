import os
import requests # requests 模組在目前版本中並未直接使用於核心轉發邏輯 (除了被註解的 Imgur)
import time   # time 模組在目前版本中並未直接使用 (除了被註解的 Imgur)
import logging
import uuid
import mimetypes
from flask import Flask, request, abort, send_from_directory

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

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

GROUP_A = os.getenv("GROUP_ID_A_LEESISTERS", 'C7688c1f2bc678001d3c49d77aef1e888')
GROUP_B = os.getenv("GROUP_ID_B_ELSA_ANNA", 'C588382cd48e689885e3f9fc5feae4f90')
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
        api = MessagingApi(api_client)
        group_a_display_name = f"[{GROUP_A_NAME}]" if GROUP_A_NAME else ""

        if isinstance(event.message, TextMessageContent):
            text_to_send = f"{group_a_display_name} {event.message.text}".strip()
            logging.info(f"轉發文字訊息至 {GROUP_B}: {text_to_send}")
            api.push_message_with_http_info(
                PushMessageRequest(
                    to=GROUP_B,
                    messages=[TextMessage(text=text_to_send)]
                )
            )
                
        elif isinstance(event.message, ImageMessageContent):
            message_id = event.message.id
            logging.info(f"接收到圖片訊息，ID: {message_id}")
            
            if not APP_BASE_URL:
                logging.error("APP_BASE_URL 未設定，無法處理圖片轉發。")
                try: # 嘗試通知來源群組
                    api.push_message_with_http_info(
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
                # 1. 下載圖片內容 (使用 v3 的正確方法)
                logging.debug(f"準備下載圖片內容: {message_id}")
                api_response = api.get_message_content_with_http_info(message_id=message_id)
                # api_response.data 包含 bytes
                # api_response.headers 包含 headers
                # api_response.status_code 包含狀態碼

                if api_response.status_code == 200:
                    message_content_bytes = api_response.data
                    content_type_header = api_response.headers.get('Content-Type', 'image/jpeg') # 預設為 jpeg
                    logging.debug(f"圖片內容下載成功，Content-Type: {content_type_header}, 大小: {len(message_content_bytes)} bytes")
                else:
                    logging.error(f"下載圖片內容失敗，狀態碼: {api_response.status_code}, 訊息 ID: {message_id}")
                    # 根據需要回覆錯誤訊息
                    # api.reply_message_with_http_info(...)
                    return


                if message_content_bytes:
                    if not mimetypes.inited:
                        mimetypes.init() # 初始化 mimetypes，如果還沒的話

                    extension = mimetypes.guess_extension(content_type_header, strict=False)
                    if not extension:
                        logging.warning(f"無法從 Content-Type '{content_type_header}' 推斷副檔名，預設為 .jpg")
                        extension = ".jpg"
                    # 確保副檔名以 '.' 開頭
                    if not extension.startswith('.'):
                        extension = '.' + extension

                    unique_filename = f"{uuid.uuid4()}{extension}"
                    filepath = os.path.join(TEMP_IMAGE_DIR_PATH, unique_filename)

                    # 2. 儲存圖片到臨時檔案
                    with open(filepath, "wb") as f:
                        f.write(message_content_bytes)
                    logging.info(f"圖片已臨時儲存於: {filepath}")

                    # 3. 產生公開 URL
                    public_image_url = f"{APP_BASE_URL.rstrip('/')}/{TEMP_IMAGE_DIR_NAME}/{unique_filename}"
                    logging.info(f"產生公開圖片 URL: {public_image_url}")

                    # 4. 建立並發送 ImageMessage 到 GROUP_B
                    image_msg_to_forward = ImageMessage(
                        original_content_url=public_image_url,
                        preview_image_url=public_image_url
                    )

                    messages_to_send = [image_msg_to_forward]
                    if GROUP_A_DISPLAY_NAME: # 如果設定了來源群組顯示名稱，則加上
                        text_label_msg = TextMessage(text=f"圖片來自: {GROUP_A_DISPLAY_NAME}")
                        messages_to_send.append(text_label_msg)


                    logging.info(f"準備轉發圖片訊息至群組 {GROUP_B_ID}")
                    api.push_message_with_http_info(
                        PushMessageRequest(
                            to=GROUP_B_ID,
                            messages=messages_to_send
                        )
                    )
                    logging.info(f"圖片訊息已成功轉發至群組 {GROUP_B_ID}")

                else: # message_content_bytes 為空 (理論上如果 status_code 200 應該有內容)
                    logging.error(f"下載後圖片內容為空，訊息 ID: {message_id}")
                    # api.reply_message_with_http_info(...)

            except ApiException as e:
                logging.error(f"LINE API 操作失敗 (圖片處理: {message_id}): {e.status} {e.reason} {e.body}", exc_info=True)
                # 根據錯誤類型決定是否回覆
                # if e.status == 401: # Unauthorized
                #     logging.error("LINE API 認證失敗，請檢查 Channel Access Token。")
                # elif e.status == 400: # Bad Request
                #     logging.error(f"LINE API 請求錯誤: {e.body}")
                # api.reply_message_with_http_info(...)
            except FileNotFoundError: # 如果 TEMP_IMAGE_DIR_PATH 突然消失 (不太可能，但以防萬一)
                logging.error(f"臨時圖片目錄 {TEMP_IMAGE_DIR_PATH} 不存在，無法儲存圖片。", exc_info=True)
            except IOError as e_io:
                logging.error(f"儲存圖片 {filepath} 時發生 IO 錯誤: {e_io}", exc_info=True)
            except Exception as e:
                logging.error(f"處理圖片訊息 {message_id} 時發生未預期錯誤: {e}", exc_info=True)
                # api.reply_message_with_http_info(...)
            finally:
                # 在處理完畢後 (無論成功或失敗)，嘗試刪除臨時檔案
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        logging.info(f"已刪除臨時圖片檔案: {filepath}")
                    except OSError as e_remove:
                        # 如果刪除失敗，記錄錯誤但不要讓整個請求失敗
                        logging.error(f"刪除臨時圖片檔案 {filepath} 失敗: {e_remove}", exc_info=True)
                elif filepath: # filepath 有值但檔案不存在 (可能在儲存前就出錯，或已被其他程序移除)
                    logging.warning(f"嘗試刪除臨時檔案 {filepath}，但該檔案不存在。")

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
