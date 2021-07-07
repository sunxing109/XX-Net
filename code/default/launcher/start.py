#!/usr/bin/env python3
# coding:utf-8

import os
import sys
import time
import traceback
from datetime import datetime
import atexit

# reduce resource request for threading
# for OpenWrt
import threading
try:
    threading.stack_size(128 * 1024)
except:
    pass

try:
    import tracemalloc
    tracemalloc.start(10)
except:
    pass

current_path = os.path.dirname(os.path.abspath(__file__))
default_path = os.path.abspath(os.path.join(current_path, os.pardir))
data_path = os.path.abspath(os.path.join(default_path, os.pardir, os.pardir, 'data'))
data_launcher_path = os.path.join(data_path, 'launcher')
noarch_lib = os.path.abspath(os.path.join(default_path, 'lib', 'noarch'))
sys.path.append(noarch_lib)

running_file = os.path.join(data_launcher_path, "Running.Lck")


def create_data_path():
    if not os.path.isdir(data_path):
        os.mkdir(data_path)

    if not os.path.isdir(data_launcher_path):
        os.mkdir(data_launcher_path)

    data_gae_proxy_path = os.path.join(data_path, 'gae_proxy')
    if not os.path.isdir(data_gae_proxy_path):
        os.mkdir(data_gae_proxy_path)

create_data_path()


from xlog import getLogger
log_file = os.path.join(data_launcher_path, "launcher.log")
xlog = getLogger("launcher", file_name=log_file)


def uncaughtExceptionHandler(etype, value, tb):
    if etype == KeyboardInterrupt:  # Ctrl + C on console
        xlog.warn("KeyboardInterrupt, exiting...")
        module_init.stop_all()
        os._exit(0)

    exc_info = ''.join(traceback.format_exception(etype, value, tb))
    print(("uncaught Exception:\n" + exc_info))
    with open(os.path.join(data_launcher_path, "error.log"), "a") as fd:
        now = datetime.now()
        time_str = now.strftime("%b %d %H:%M:%S.%f")[:19]
        fd.write("%s type:%s value=%s traceback:%s" % (time_str, etype, value, exc_info))
    xlog.error("uncaught Exception, type=%s value=%s traceback:%s", etype, value, exc_info)
    # sys.exit(1)


sys.excepthook = uncaughtExceptionHandler


has_desktop = True


def unload(module):
    for m in list(sys.modules.keys()):
        if m == module or m.startswith(module + "."):
            del sys.modules[m]

    for p in list(sys.path_importer_cache.keys()):
        if module in p:
            del sys.path_importer_cache[p]

    try:
        del module
    except:
        pass


try:
    sys.path.insert(0, noarch_lib)
    import OpenSSL as oss_test
    xlog.info("use build-in openssl lib")
except Exception as e1:
    xlog.info("import build-in openssl fail:%r", e1)
    sys.path.pop(0)
    del sys.path_importer_cache[noarch_lib]
    unload("OpenSSL")
    unload("cryptography")
    unload("cffi")
    try:
        import OpenSSL
    except Exception as e2:
        xlog.exception("import system python-OpenSSL fail:%r", e2)
        print("Try install python-openssl\r\n")
        input("Press Enter to continue...")
        os._exit(0)

import sys_platform
from config import config
import web_control
import module_init
import update
import update_from_github
import download_modules


def exit_handler():
    print('Stopping all modules before exit!')
    module_init.stop_all()
    web_control.stop()

atexit.register(exit_handler)


def main():
    # change path to launcher
    global __file__
    __file__ = os.path.abspath(__file__)
    if os.path.islink(__file__):
        __file__ = getattr(os, 'readlink', lambda x: x)(__file__)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if sys.platform == "win32" and config.show_compat_suggest:
        import win_compat_suggest
        win_compat_suggest.main()

    current_version = update_from_github.current_version()

    xlog.info("start XX-Net %s", current_version)

    web_control.confirm_xxnet_not_running()

    import post_update
    post_update.check()

    allow_remote = 0
    no_mess_system = 0
    if len(sys.argv) > 1:
        for s in sys.argv[1:]:
            xlog.info("command args:%s", s)
            if s == "-allow_remote":
                allow_remote = 1
            elif s == "-no_mess_system":
                no_mess_system = 1

    if allow_remote or config.allow_remote_connect:
        xlog.info("start with allow remote connect.")
        module_init.xargs["allow_remote"] = 1

    if os.getenv("XXNET_NO_MESS_SYSTEM", "0") != "0" or no_mess_system or config.no_mess_system:
        xlog.info("start with no_mess_system, no CA will be imported to system.")
        module_init.xargs["no_mess_system"] = 1

    if os.path.isfile(running_file):
        restart_from_except = True
    else:
        restart_from_except = False

    module_init.start_all_auto()
    web_control.start(allow_remote)

    if has_desktop and config.popup_webui == 1 and not restart_from_except:
        host_port = config.control_port
        import webbrowser
        webbrowser.open("http://localhost:%s/" % host_port)

    update.start()
    if has_desktop:
        download_modules.start_download()
    update_from_github.cleanup()

    if config.show_systray:
        sys_platform.sys_tray.serve_forever()
    else:
        while True:
            time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:  # Ctrl + C on console
        module_init.stop_all()
        os._exit(0)
        sys.exit()
    except Exception as e:
        xlog.exception("launcher except:%r", e)
        input("Press Enter to continue...")
