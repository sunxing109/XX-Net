xxnet_version = ""
client_uuid = ""

running = True
protocol_version = 2
last_refresh_time = 0
login_process = False
data_path = None

config = None
http_client = None
cloudflare_front = None
cloudfront_front = None
tls_relay_front = None

session = None
socks5_server = None
last_api_error = ""

promote_code = ""
promoter = ""
quota_list = {}
quota = 0
paypal_button_id = ""
plans = {}

server_host = ""
server_port = 0
selectable = []
balance = 0

stat = {
    "roundtrip_num": 0,
    "slow_roundtrip": 0,
    "timeout_roundtrip": 0,
    "resend": 0
}