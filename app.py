import os
import requests
import time
import logging
import uuid # <<< 新增，用於產生唯一檔名
import mimetypes # <<< 新增，用於猜測檔案類型
from flask import Flask, request, abort, send_from_directory # <<< send_from_directory 新增

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

# 設定日誌記錄
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)


# 從 .env 環境變數中取得 token / secret
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
#IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")
#IMGUR_UPLOAD_URL = "https://api.imgur.com/3/image"

GROUP_A = os.getenv("GROUP_ID_A_LEESISTERS", 'C7688c1f2bc678001d3c49d77aef1e888') #Davis & Zoe - Education
GROUP_B = os.getenv("GROUP_ID_B_ELSA_ANNA", 'C588382cd48e689885e3f9fc5feae4f90') #Davis & Zoe - 家庭教育
#GROUP_B = os.getenv("GROUP_ID_B_ELSA_ANNA", 'C8165f7f0ac4ddd169e8ae1dbba6fd2d8')  #奕涵詠涵生活大小事
GROUP_A_NAME = os.getenv("GROUP_A_NAME", "LeeSisters")
DEFAULT_VIDEO_PREVIEW_IMAGE_URL = os.getenv("DEFAULT_VIDEO_PREVIEW_IMAGE_URL"),'https://api.imgur.com/3/uploa'


# <<< 新增：臨時圖片儲存設定 >>>
TEMP_IMAGE_DIR_NAME = "line_temp_images" # 臨時圖片儲存的資料夾名稱
TEMP_IMAGE_DIR_PATH = os.path.join(os.path.dirname(__file__), TEMP_IMAGE_DIR_NAME) # 完整路徑
if not os.path.exists(TEMP_IMAGE_DIR_PATH):
    try:
        os.makedirs(TEMP_IMAGE_DIR_PATH)
        logging.info(f"已建立臨時圖片資料夾: {TEMP_IMAGE_DIR_PATH}")
    except OSError as e:
        logging.error(f"建立臨時圖片資料夾失敗: {e}")
        # 嚴重錯誤，可能需要停止應用程式或採取其他措施
        # exit() # 或者拋出異常

# <<< 新增：從環境變數讀取應用程式的公開基礎 URL >>>
# 例如：APP_BASE_URL=https://your-app-name.onrender.com
APP_BASE_URL = os.getenv("APP_BASE_URL")
if not APP_BASE_URL:
    logging.warning("環境變數 APP_BASE_URL 未設定。圖片轉發功能可能無法正常運作，因為無法產生公開的圖片 URL。")


# 如果不再使用 Imgur，可以移除 upload_to_imgur 函數，或保留它用於影片等其他內容
# def upload_to_imgur(content_bytes, max_retries=3): ...

@app.route("/callback", methods=['POST'])
def callback():
    # ... (保持不變) ...
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    logging.info(f"接收到請求: {body[:300]}...") # 記錄部分 body 內容以供調試
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("無效的簽名。請檢查您的 Channel Secret。")
        abort(400, "Invalid signature")
    except Exception as e:
        logging.error(f"處理回呼時發生錯誤: {e}", exc_info=True) # 記錄堆疊追蹤
        abort(500, "Internal server error")
    return 'OK'

# <<< 新增：用於提供臨時圖片的 Flask 路由 >>>
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
            # ... (文字訊息處理保持不變) ...
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
                # 可以考慮發送一條通知給管理者或來源群組
                api.push_message_with_http_info(
                    PushMessageRequest(
                        to=event.source.group_id, # 或某個管理員ID
                        messages=[TextMessage(text="[系統通知] 圖片轉發功能因伺服器設定問題暫停。")]
                    )
                )
                return

            filepath = None # 初始化 filepath
            try:
                message_content_bytes = api.get_message_content(message_id=message_id)
                
                if message_content_bytes:
                    # 1. 確定檔案類型和副檔名
                    content_type = api.api_client.last_response.headers.get('Content-Type', 'image/jpeg')
                    if not mimetypes.inited:
                        mimetypes.init()
                    
                    extension = mimetypes.guess_extension(content_type, strict=False) # strict=False 允許 .jpe 等
                    if not extension:
                        if 'jpeg' in content_type.lower():
                            extension = '.jpg'
                        elif 'png' in content_type.lower():
                            extension = '.png'
                        elif 'gif' in content_type.lower():
                            extension = '.gif'
                        else:
                            extension = '.jpg' # 預設副檔名
                            logging.warning(f"無法從 Content-Type '{content_type}' 推斷副檔名，預設為 {extension}")
                    # 確保副檔名以點開頭
                    if extension and not extension.startswith('.'):
                        extension = '.' + extension
                    
                    # 2. 儲存圖片到臨時檔案
                    unique_filename = f"{uuid.uuid4()}{extension}"
                    filepath = os.path.join(TEMP_IMAGE_DIR_PATH, unique_filename)
                    
                    with open(filepath, "wb") as f:
                        f.write(message_content_bytes)
                    logging.info(f"圖片已臨時儲存於: {filepath}")
                    
                    # 3. 產生公開 URL
                    public_image_url = f"{APP_BASE_URL.rstrip('/')}/{TEMP_IMAGE_DIR_NAME}/{unique_filename}"
                    
                    # 4. 建立並發送 ImageMessage
                    image_msg = ImageMessage(
                        original_content_url=public_image_url,
                        preview_image_url=public_image_url # 對於靜態圖片，兩者通常可以相同
                    )
                    text_label = TextMessage(text=group_a_display_name) if group_a_display_name else None
                    
                    messages_to_send = [image_msg]
                    if text_label:
                        messages_to_send.append(text_label)

                    logging.info(f"轉發圖片訊息至 {GROUP_B} (本地 URL: {public_image_url})")
                    api.push_message_with_http_info(
                        PushMessageRequest(
                            to=GROUP_B,
                            messages=messages_to_send
                        )
                    )
                    
                    # 5. 檔案清理 (重要!)
                    # 這裡僅記錄，實際清理機制需要另外實現。
                    # 例如，可以設定一個背景任務定期清理 TEMP_IMAGE_DIR_PATH 中超過一定時間的檔案。
                    # 或者，如果您的平台在重啟時會清除臨時檔案，且圖片的有效時間不需要太長，也可以依賴它。
                    # 為了避免立即刪除導致 LINE 伺服器抓取失敗，這裡不直接刪除。
                    logging.info(f"臨時圖片 {filepath} 需要後續清理機制處理。")

                else:
                    logging.error(f"無法從 LINE 下載圖片內容: {message_id}")

            except Exception as e:
                logging.error(f"處理圖片訊息 {message_id} 時發生錯誤: {e}", exc_info=True)
                if filepath and os.path.exists(filepath): # 如果發生錯誤且檔案已建立，嘗試刪除
                    try:
                        os.remove(filepath)
                        logging.info(f"錯誤處理：已刪除臨時檔案 {filepath}")
                    except OSError as e_remove:
                        logging.error(f"錯誤處理：刪除臨時檔案 {filepath} 失敗: {e_remove}")

        elif isinstance(event.message, VideoMessageContent):
            # ... (影片訊息處理，如果仍使用 Imgur，則保持不變，否則也需類似處理) ...
            # 影片的處理會更複雜，因為影片檔案通常更大，且 VideoMessage 也需要 original_content_url 和 preview_image_url。
            # 如果要讓伺服器處理影片，挑戰會更大。目前暫時保持原樣或提示用戶。
            logging.info("影片訊息轉發目前仍建議使用外部託管（如 Imgur）或需要更複雜的本地處理。")
            # 這裡可以複製原始的 Imgur 上傳邏輯，或者發送一條提示訊息。
            # 為了範例的集中性，這裡暫不詳細展開影片的本地託管。
            # 以下是原始的 Imgur 邏輯 (簡化版)
            message_id = event.message.id
            logging.info(f"接收到影片訊息，ID: {message_id}。將嘗試使用 Imgur 上傳。")
            try:
                message_content = api.get_message_content(message_id=message_id)
                if message_content:
                    # 確保 upload_to_imgur 函數仍然存在且 IMGUR_CLIENT_ID 已設定
                    if os.getenv("IMGUR_CLIENT_ID") and 'upload_to_imgur' in globals():
                        imgur_url = upload_to_imgur(message_content) # 假設 upload_to_imgur 函數還在
                        if imgur_url:
                            preview_url_to_use = DEFAULT_VIDEO_PREVIEW_IMAGE_URL or imgur_url # 簡化
                            video_msg = VideoMessage(
                                original_content_url=imgur_url,
                                preview_image_url=preview_url_to_use
                            )
                            text_label = TextMessage(text=group_a_display_name) if group_a_display_name else None
                            messages_to_send = [video_msg]
                            if text_label: messages_to_send.append(text_label)
                            
                            api.push_message_with_http_info(
                                PushMessageRequest(to=GROUP_B, messages=messages_to_send)
                            )
                        else:
                            logging.error
                            

""""
def upload_to_imgur(img_bytes, max_retries=5):
    headers = {"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"}
    files = {"image": img_bytes}
    retries = 0
    
    while retries < max_retries:
        resp = requests.post(IMGUR_UPLOAD_URL, headers=headers, files=files)
        
        if resp.status_code == 200:
            data = resp.json()
            try:
                return data["data"]["link"] if data.get("success") else None
            except KeyError as e:
                print(f"錯誤：{e}")
                return None
        else:
            print(f"上傳失敗，狀態碼：{resp.status_code}，重試中...")
            retries += 1
            time.sleep(1)  # 等待 1 秒後重試
            
    print("上傳失敗，已達最大重試次數。")
    return None


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    return 'OK'


@handler.add(MessageEvent)
def handle_message(event):

    if event.source.type != "group" or event.source.group_id != GROUP_A:
        return

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)

        if isinstance(event.message, TextMessageContent):
            text = f"[{GROUP_A_NAME}] {event.message.text}"
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

                #test
                api.push_message_with_http_info(
                    PushMessageRequest(
                        to=GROUP_B,
                        messages=[TextMessage(text=f"url：{url}")]
                    )
                )


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