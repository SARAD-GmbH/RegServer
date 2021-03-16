# pylint: skip-file
import socket
import traceback
import time
import logging
from registrationserver2 import theLogger
import registrationserver2

port: tuple = ("127.0.0.1", 54626)
_csock: socket.socket

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


def testingServ():
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _sock.bind(("", 0))
    port = _sock.getsockname()
    theLogger.info(port)
    _sock.settimeout(0.5)
    _sock.listen()
    cs: socket
    while True:
        try:
            (cs, csi) = _sock.accept()
            while True:
                data = cs.recv(9002)
                theLogger.info(data)
                if not data:
                    break
        except BaseException as error:  # pylint: disable=W0703
            theLogger.error(
                f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
            )
        finally:
            time.sleep(3)


def testingClient():
    registrationserver2.test._csock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    registrationserver2.test._csock.setsockopt(
        socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
    )
    registrationserver2.test._csock.connect(registrationserver2.test.port)


if __name__ == "__main__":

    try:
        raise BaseException("x")
    except NameError as error:
        print("!NE")
    except BaseException as error:
        print(
            f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-" }'
        )
    except:
        print("?!?")
    finally:
        pass
    test = {"CMD": "Test"}
    print(test)
    print(isinstance(test, dict))
    print(test.get("CMD", None))
    testingServ()
