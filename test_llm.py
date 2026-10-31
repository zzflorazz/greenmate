"""Offline tests: use the SDK's HTTP transport dependency; no real API calls."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx2
from openai import AsyncOpenAI

import llm
import db
import rag
import state
from main import app
from state import DEFAULT_STATE, get_state, update_state


class AskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for target, options in (
            ('main.build_knowledge_index', {'return_value': {}}),
            ('main.vector_search', {'side_effect': rag.simple_search}),
        ):
            mock_patch = patch(target, **options)
            mock_patch.start()
            self.addCleanup(mock_patch.stop)
        self.previous = state._current_state
        self.temp_dir = TemporaryDirectory()
        self.db_patch = patch("db.DB_PATH", str(Path(self.temp_dir.name) / "test.db"))
        self.db_patch.start()
        self.lifespan = app.router.lifespan_context(app)
        await self.lifespan.__aenter__()
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://greenmate.test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        state._current_state = self.previous
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def sdk_client(self, handler):
        def factory(**kwargs):
            return AsyncOpenAI(
                **kwargs,
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            )
        return factory

    async def test_sdk_request_and_snapshot(self):
        snapshot = update_state({"temperature": 26, "humidity": 72, "light": 8500})
        question = "当前绿萝需要浇水吗？"

        def handler(request):
            self.assertEqual(str(request.url), llm.LLM_BASE_URL.rstrip("/") + "/chat/completions")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], llm.LLM_MODEL)
            self.assertEqual(payload["messages"], llm.build_messages(snapshot, question, knowledge=rag.simple_search(question)))
            self.assertIn(json.dumps(snapshot, ensure_ascii=False), payload["messages"][1]["content"])
            self.assertIn("SIMULATED", payload["messages"][0]["content"])
            # Simulate a concurrent state change while the upstream request is pending.
            update_state({"humidity": 40})
            return httpx2.Response(200, json={
                "id": "offline-test", "object": "chat.completion", "created": 0,
                "model": llm.LLM_MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "模拟回答：26°C、72%、8500 lux，来源 SIMULATED。"}, "finish_reason": "stop"}],
            })

        with patch.dict(os.environ, {"GREENMATE_API_KEY": "offline-test-key"}), patch("llm.AsyncOpenAI", side_effect=self.sdk_client(handler)):
            response = await self.client.post("/api/ask", json={"question": question})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(set(result), {"answer", "used_state", "source_type"})
        self.assertEqual(result["used_state"], snapshot)
        self.assertEqual(result["source_type"], "SIMULATED")
        self.assertIn("8500", result["answer"])
        self.assertEqual(get_state()["humidity"], 40)

    async def test_missing_key(self):
        with patch.dict(os.environ, {"GREENMATE_API_KEY": ""}):
            response = await self.client.post("/api/ask", json={"question": "需要浇水吗？"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("GREENMATE_API_KEY", response.json()["detail"])

    async def test_invalid_questions(self):
        for payload in ({}, {"question": "   "}, {"question": 12}, {"question": "a" * 2001}):
            response = await self.client.post("/api/ask", json=payload)
            self.assertEqual(response.status_code, 422)

    async def test_upstream_failure_is_sanitized(self):
        def handler(request):
            return httpx2.Response(401, json={"error": {"message": "sensitive-upstream-detail"}})
        with patch.dict(os.environ, {"GREENMATE_API_KEY": "offline-test-key"}), patch("llm.AsyncOpenAI", side_effect=self.sdk_client(handler)):
            response = await self.client.post("/api/ask", json={"question": "需要浇水吗？"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("sensitive-upstream-detail", response.text)

    async def test_existing_routes(self):
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn('href="/conversation"', response.text)
        conversation = await self.client.get('/conversation')
        self.assertEqual(conversation.status_code, 200)
        self.assertIn('id="ask-form"', conversation.text)
        response = await self.client.post("/api/state", json={"light": 10000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.client.get("/api/state")).json()["light"], 10000)
        self.assertEqual(DEFAULT_STATE["light"], 12000)

    async def test_two_turns_and_history_after_restart(self):
        sent_messages = []

        def handler(request):
            messages = json.loads(request.content)["messages"]
            sent_messages.append(messages)
            return httpx2.Response(200, json={
                "id": "memory-test", "object": "chat.completion", "created": 0,
                "model": llm.LLM_MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": f"离线测试回答{len(sent_messages)}"}, "finish_reason": "stop"}],
            })

        questions = ["需要浇水吗？", "那施肥呢？", "刚才的建议是什么？"]
        with patch.dict(os.environ, {"GREENMATE_API_KEY": "offline-test-key"}), patch("llm.AsyncOpenAI", side_effect=self.sdk_client(handler)):
            for question in questions[:2]:
                response = await self.client.post("/api/ask", json={"question": question})
                self.assertEqual(response.status_code, 200)
            self.assertEqual([m["role"] for m in sent_messages[1]], ["system", "user", "assistant", "user"])
            self.assertEqual(sent_messages[1][1], {"role": "user", "content": questions[0]})
            self.assertEqual(sent_messages[1][2], {"role": "assistant", "content": "离线测试回答1"})
            self.assertEqual(sum(questions[1] in m["content"] for m in sent_messages[1] if m["role"] == "user"), 1)
            history = (await self.client.get("/api/history")).json()
            self.assertEqual([m["role"] for m in history], ["user", "assistant", "user", "assistant"])
            self.assertTrue(all(set(m) == {"id", "role", "content", "timestamp"} for m in history))

            # Restart the application lifecycle using the same SQLite file.
            await self.lifespan.__aexit__(None, None, None)
            state._current_state = None
            self.lifespan = app.router.lifespan_context(app)
            await self.lifespan.__aenter__()
            self.assertEqual((await self.client.get("/api/history")).json(), history)
            response = await self.client.post("/api/ask", json={"question": questions[2]})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(sent_messages[2]), 6)
        self.assertEqual(sent_messages[2][1:5], [{"role": m["role"], "content": m["content"]} for m in history])

    async def test_history_and_context_limits(self):
        self.assertEqual((await self.client.get("/api/history")).json(), [])
        for index in range(24):
            db.save_chat("user" if index % 2 == 0 else "assistant", f"message-{index}")
        recent = db.load_recent_chat()
        self.assertEqual([m["content"] for m in recent], [f"message-{i}" for i in range(14, 24)])
        history = (await self.client.get("/api/history")).json()
        self.assertEqual([m["content"] for m in history], [f"message-{i}" for i in range(4, 24)])
        from unittest.mock import AsyncMock
        generate = AsyncMock(return_value="离线测试回答")
        with patch("main.generate_answer", generate):
            response = await self.client.post("/api/ask", json={"question": "下一步呢？"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.await_args.args[2], recent)
        self.assertEqual(len(llm.build_messages(get_state(), "下一步呢？", recent)), 12)

    async def test_failed_call_saves_question_without_fake_answer(self):
        with patch.dict(os.environ, {"GREENMATE_API_KEY": ""}):
            response = await self.client.post("/api/ask", json={"question": "需要浇水吗？"})
        self.assertEqual(response.status_code, 503)
        history = (await self.client.get("/api/history")).json()
        self.assertEqual([(m["role"], m["content"]) for m in history], [("user", "需要浇水吗？")])

    async def test_chat_storage_preserves_content_and_survives_new_process(self):
        import subprocess
        import sys
        content = "绿萝's 养护建议；DROP TABLE chat_history;"
        db.save_chat("user", content)
        result = subprocess.run(
            [sys.executable, "-c", "import db, json, sys; db.DB_PATH = sys.argv[1]; db.init_db(); print(json.dumps(db.load_recent_chat(), ensure_ascii=False))", db.DB_PATH],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(json.loads(result.stdout)[0]["content"], content)
        self.assertEqual(db.load_recent_chat(0), [])


if __name__ == "__main__":
    unittest.main()
