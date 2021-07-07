import os
import sys
from . import apis

from xlog import getLogger
xlog = getLogger("smart_router")
xlog.set_buffer(500)

current_path = os.path.dirname(os.path.abspath(__file__))
launcher_path = os.path.abspath( os.path.join(current_path, os.pardir, os.pardir, "launcher"))

root_path = os.path.abspath(os.path.join(current_path, os.pardir, os.pardir))
data_path = os.path.abspath(os.path.join(root_path, os.pardir, os.pardir, 'data', "smart_router"))
if launcher_path not in sys.path:
    sys.path.append(launcher_path)


import xconfig
import simple_http_server

try:
    from module_init import proc_handler
except:
    xlog.info("launcher not running")
    proc_handler = None


from . import global_var as g
from . import dns_server
from . import dns_query
from . import host_records
from . import user_rules
from . import proxy_handler
from . import web_control
from . import connect_manager
from . import pac_server
from . import pipe_socks
from . import ip_region
from . import gfwlist

ready = False


def is_ready():
    global ready
    return ready


def load_config():
    global g
    if not os.path.isdir(data_path):
        os.mkdir(data_path)

    config_path = os.path.join(data_path, 'config.json')
    config = xconfig.Config(config_path)

    config.set_var("PROXY_ENABLE", 0)
    config.set_var("PROXY_TYPE", "HTTP")
    config.set_var("PROXY_HOST", "")
    config.set_var("PROXY_PORT", 0)
    config.set_var("PROXY_USER", "")
    config.set_var("PROXY_PASSWD", "")

    config.set_var("dns_bind_ip", "127.0.0.1")
    config.set_var("dns_port", 53)
    config.set_var("dns_backup_port", 8053)

    config.set_var("proxy_bind_ip", "127.0.0.1")
    config.set_var("proxy_port", 8086)

    config.set_var("dns_cache_size", 200)
    config.set_var("pip_cache_size", 32*1024)
    config.set_var("ip_cache_size", 1000)
    config.set_var("dns_ttl", 60*30)
    config.set_var("direct_split_SNI", 1)

    config.set_var("pac_policy", "black_GAE")
    config.set_var("country_code", "CN")
    config.set_var("auto_direct", 1)
    config.set_var("auto_direct6", 0)
    config.set_var("auto_gae", 1)
    config.set_var("enable_fake_ca", 1)
    config.set_var("block_advertisement", 1)

    config.set_var("log_debug", 0)

    config.load()
    if config.PROXY_ENABLE:
        xlog.info("use LAN proxy:%s://%s:%d/", config.PROXY_TYPE,
                  config.PROXY_HOST, config.PROXY_PORT)

    g.config = config


def start(args):
    global proc_handler, ready, g

    if not proc_handler:
        return False

    if "gae_proxy" in proc_handler:
        g.gae_proxy = proc_handler["gae_proxy"]["imp"].local
        g.gae_proxy_listen_port = g.gae_proxy.config.config.listen_port
    else:
        xlog.debug("gae_proxy not running")

    if "x_tunnel" in proc_handler:
        g.x_tunnel = proc_handler["x_tunnel"]["imp"].local
        g.x_tunnel_socks_port = g.x_tunnel.global_var.config.socks_port
    else:
        xlog.debug("x_tunnel not running")

    load_config()
    g.gfwlist = gfwlist.GfwList()
    g.ip_region = ip_region.IpRegion()

    g.domain_cache = host_records.DomainRecords(os.path.join(data_path, "domain_records.txt"),
                                                capacity=g.config.dns_cache_size, ttl=g.config.dns_ttl)
    g.ip_cache = host_records.IpRecord(os.path.join(data_path, "ip_records.txt"),
                                       capacity=g.config.ip_cache_size)

    g.user_rules = user_rules.Config()

    connect_manager.load_proxy_config()
    g.connect_manager = connect_manager.ConnectManager()
    g.pipe_socks = pipe_socks.PipeSocks(g.config.pip_cache_size)
    g.pipe_socks.run()
    g.dns_query = dns_query.CombineDnsQuery()

    allow_remote = args.get("allow_remote", 0)

    listen_ips = g.config.proxy_bind_ip
    if isinstance(listen_ips, str):
        listen_ips = [listen_ips]
    else:
        listen_ips = list(listen_ips)

    if allow_remote and ("0.0.0.0" not in listen_ips or "::" not in listen_ips):
        listen_ips = [("0.0.0.0")]
    addresses = [(listen_ip, g.config.proxy_port) for listen_ip in listen_ips]

    g.proxy_server = simple_http_server.HTTPServer(addresses,
                                                   proxy_handler.ProxyServer, logger=xlog)
    g.proxy_server.start()
    xlog.info("Proxy server listen:%s:%d.", listen_ips, g.config.proxy_port)

    listen_ips = g.config.dns_bind_ip
    if isinstance(listen_ips, str):
        listen_ips = [listen_ips]
    else:
        listen_ips = list(listen_ips)
    if allow_remote and ("0.0.0.0" not in listen_ips or "::" not in listen_ips):
        listen_ips.append("0.0.0.0")

    g.dns_srv = dns_server.DnsServer(
        bind_ip=listen_ips, port=g.config.dns_port,
        backup_port=g.config.dns_backup_port,
        ttl=g.config.dns_ttl)
    ready = True
    g.dns_srv.server_forever()


def stop():
    global ready

    g.domain_cache.save(True)
    g.ip_cache.save(True)

    g.connect_manager.stop()
    g.pipe_socks.stop()
    g.dns_query.stop()

    g.dns_srv.stop()
    g.proxy_server.shutdown()
    ready = False
