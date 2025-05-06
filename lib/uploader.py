import os
import pickle
import logging
import time
import sys
import requests
import win32crypt

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_appdata_dir():
    """
    Returns the path to %AppData%\\YouTubeUploader on Windows.
    Creates it if it doesn't exist.
    """
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    folder = os.path.join(appdata, "YouTubeUploader")
    os.makedirs(folder, exist_ok=True)
    return folder


CLIENT_SECRET_FILE = resource_path(os.path.join("lib", "client_secret.json"))
ENCRYPTED_TOKEN_FILE = os.path.join(get_appdata_dir(), "token.enc")


class UploadStatus:
    def __init__(self):
        self.progress = 0
        self.step = ""
        self.video_url = ""
        self.error = None


def encrypt_token(creds):
    data = pickle.dumps(creds)
    encrypted = win32crypt.CryptProtectData(data, None, None, None, None, 0)
    with open(ENCRYPTED_TOKEN_FILE, "wb") as f:
        f.write(encrypted)


def decrypt_token():
    with open(ENCRYPTED_TOKEN_FILE, "rb") as f:
        encrypted = f.read()
    decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
    return pickle.loads(decrypted)


def authenticate():
    """
    Authenticates with Google using OAuth2 and DPAPI-protected token.
    """
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if os.path.exists(ENCRYPTED_TOKEN_FILE):
        try:
            creds = decrypt_token()
        except Exception as e:
            logging.error("Failed to decrypt token: %s", e)
            os.remove(ENCRYPTED_TOKEN_FILE)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logging.error("Error refreshing credentials: %s", e)
                os.remove(ENCRYPTED_TOKEN_FILE)
                creds = None

        if not creds:
            try:
                if not os.path.exists(CLIENT_SECRET_FILE):
                    raise FileNotFoundError(f"client_secret.json not found at {CLIENT_SECRET_FILE}")
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=0, authorization_url_params={"access_type": "online"})
            except FileNotFoundError as e:
                logging.error(f"Client secret file not found: {e}")
                raise
            except Exception as e:
                logging.error(f"Auth error: {e}")
                raise

        encrypt_token(creds)

    return build("youtube", "v3", credentials=creds)


def get_playlists():
    youtube = authenticate()
    request = youtube.playlists().list(part="id,snippet", mine=True, maxResults=10)
    response = request.execute()
    return response.get("items", [])


def add_video_to_playlist(youtube, video_id, playlist_id):
    try:
        req = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )
        return req.execute()
    except Exception as e:
        logging.error("Playlist add error: %s", e)
        return None


def upload_to_youtube(
    file_path,
    playlist_ids=None,
    privacy="unlisted",
    title=None,
    description=None,
    tags=None,
    callback=None,
):
    status = UploadStatus()

    if not os.path.exists(file_path):
        raise FileNotFoundError("Video file not found: " + file_path)

    from googleapiclient.http import MediaFileUpload

    title = title or os.path.basename(file_path).split(".")[0]
    description = description or ""
    tags = tags or ["video"]
    ext = os.path.splitext(file_path)[1].lower()
    mime_type = (
        "video/mp4"
        if ext == ".mp4"
        else "video/x-matroska"
        if ext == ".mkv"
        else "video/*"
    )
    youtube = authenticate()

    status.step = "Uploading"
    status.progress = 0
    if callback:
        callback(status)

    media = MediaFileUpload(
        file_path, mimetype=mime_type, chunksize=2 * 1024 * 1024, resumable=True
    )
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "20",
        },
        "status": {"privacyStatus": privacy},
    }
    try:
        req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            try:
                stat_obj, response = req.next_chunk()
            except Exception as e:
                logging.error("HTTP error during upload: %s", e)
                status.error = str(e)
                status.step = "Error"
                if callback:
                    callback(status)
                return status
            if stat_obj:
                percent = int(stat_obj.progress() * 100)
                status.progress = min(percent, 100)
                if callback:
                    callback(status)
        video_id = response.get("id")
        if not video_id:
            raise Exception("Upload failed: No video ID returned.")
    except Exception as e:
        logging.error("Upload exception: %s", e)
        status.error = str(e)
        status.step = "Error"
        if callback:
            callback(status)
        return status

    status.video_url = f"https://www.youtube.com/watch?v={video_id}"
    if callback:
        callback(status)

    status.step = "Processing"
    if callback:
        callback(status)
    while True:
        try:
            req = youtube.videos().list(
                part="status,processingDetails,player", id=video_id
            )
            resp = req.execute()
        except Exception as e:
            logging.error("HTTP error during processing check: %s", e)
            status.error = str(e)
            status.step = "Error"
            if callback:
                callback(status)
            return status
        items = resp.get("items", [])
        if items:
            item = items[0]
            proc_details = item.get("processingDetails", {})
            stat_details = item.get("status", {})
            player_details = item.get("player", {})
            upload_status = stat_details.get("uploadStatus")
            if upload_status == "uploaded":
                status.step = "Processing"
            elif upload_status == "processed":
                status.step = "Verifying"
            elif upload_status in ["failed", "rejected", "deleted"]:
                status.error = f"Video processing failed: {upload_status}"
                status.step = "Error"
                if callback:
                    callback(status)
                return status
            if callback:
                callback(status)
            if status.step == "Verifying":
                embed_html = player_details.get("embedHtml", "").strip()
                if "iframe" in embed_html:
                    status.step = "Finished"
                    status.progress = 100
                    if callback:
                        callback(status)
                    break
        else:
            status.error = "No processing details returned."
            status.step = "Error"
            if callback:
                callback(status)
            return status
        time.sleep(3)

    if playlist_ids:
        for pid in playlist_ids:
            try:
                add_video_to_playlist(youtube, video_id, pid)
            except Exception as e:
                logging.warning(f"Failed to add video to playlist {pid}: {e}")

    return status


def revoke_auth():
    """
    Revokes the current OAuth2 credentials and removes the encrypted token file.
    Returns True if revocation succeeded, False otherwise.
    """
    if not os.path.exists(ENCRYPTED_TOKEN_FILE):
        return True
    try:
        creds = decrypt_token()
    except Exception as e:
        logging.error("Failed to decrypt token for revocation: %s", e)
        os.remove(ENCRYPTED_TOKEN_FILE)
        return False

    revoke_url = "https://accounts.google.com/o/oauth2/revoke"
    params = {"token": creds.token}
    response = requests.post(
        revoke_url, params=params, headers={"content-type": "application/x-www-form-urlencoded"}
    )
    if response.status_code == 200:
        os.remove(ENCRYPTED_TOKEN_FILE)
        return True
    else:
        return False


def get_channel_info():
    youtube = authenticate()
    request = youtube.channels().list(part="snippet", mine=True)
    response = request.execute()
    items = response.get("items", [])
    if items:
        snippet = items[0].get("snippet", {})
        return {
            "title": snippet.get("title"),
            "profile_image": snippet.get("thumbnails", {}).get("default", {}).get("url"),
        }
    return None
