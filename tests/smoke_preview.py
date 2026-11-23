import http.client
import json
import os
import socket
import tempfile
import threading

import uvicorn

with tempfile.TemporaryDirectory(prefix="sunriver-smoke-") as private:
    os.umask(0o077)
    for key, name in (("UPLOAD_DIR", "submissions"), ("ALERT_QUEUE_DIR", "alerts"), ("TMPDIR", "tmp")):
        os.environ[key] = f"{private}/{name}"
        os.mkdir(os.environ[key], 0o700)

    os.environ["ENABLE_UPLOADS"] = "0"
    from server.app import app

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()

        import time
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "FastAPI failed to start"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            assert response.status == 200 and b"Complete your document exchange" in response.read()
            connection.request("GET", "/api/config")
            response = connection.getresponse()
            config = json.loads(response.read())
            assert response.status == 200 and config["enabled"] is False and not config["siteKey"]
            print("Local /api/config HTTP 200, enabled=false")
            boundary = "sunriver-test"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="documents"; filename="dummy.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
                f"%PDF-1.4\r\n%%EOF\r\n--{boundary}--\r\n"
            ).encode()
            connection.request("POST", "/api/submissions", body, {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            })
            response = connection.getresponse()
            assert response.status == 503, (response.status, response.read())
            assert not os.listdir(os.environ["UPLOAD_DIR"])
            assert not os.listdir(os.environ["ALERT_QUEUE_DIR"])
            print("Disabled upload HTTP 503; no file or notification queued")
        finally:
            connection.close()
            server.should_exit = True
            thread.join(timeout=5)
