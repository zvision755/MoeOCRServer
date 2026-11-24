import base64
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
import my_ocr


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(my_ocr.app)
        env = patch.dict(os.environ, {"MOE_SERVER_TOKEN": "test-token", "MOE_LOG_TRANSLATIONS": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.headers = {"Authorization": "Bearer test-token"}
        buf = BytesIO()
        Image.new("RGB", (64, 32), "white").save(buf, format="PNG")
        self.image = base64.b64encode(buf.getvalue()).decode()

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_auth(self):
        self.assertEqual(self.client.post("/translate", json={"img": self.image}).status_code, 401)

    def test_invalid_image(self):
        response = self.client.post("/translate", json={"img": "invalid!"}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    @patch("my_ocr.translate_text", return_value="你好")
    @patch("my_ocr.ocrmac.OCR")
    def test_translation(self, ocr, translate):
        ocr.return_value.recognize.return_value = [("こんにちは", 1.0, (0, 0, 1, 1))]
        response = self.client.post("/translate", json={"img": self.image}, headers=self.headers)
        self.assertEqual(response.json(), {"translation": "你好"})
        translate.assert_called_once_with("こんにちは")

    @patch("my_ocr.translate_text")
    @patch("my_ocr.ocrmac.OCR")
    def test_empty(self, ocr, translate):
        ocr.return_value.recognize.return_value = []
        response = self.client.post("/translate", json={"img": self.image}, headers=self.headers)
        self.assertEqual(response.json(), {"translation": ""})
        translate.assert_not_called()
