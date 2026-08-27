import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import gpt_scoring


def stream_chunk(content=None, usage=None):
    choices = []
    if content is not None:
        choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]
    return SimpleNamespace(choices=choices, usage=usage)


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_client(responses):
    completions = FakeCompletions(responses)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        completions=completions,
    )


class HttpError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class GptScoringTests(unittest.TestCase):
    def make_png(self, size=(16, 16)):
        from PIL import Image

        temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp.close()
        Image.new("RGB", size, "red").save(temp.name)
        self.addCleanup(Path(temp.name).unlink, missing_ok=True)
        return temp.name

    def score_scene(self):
        return {
            "spec": {"space_type": "study_room", "theme": "test"},
            "objects": [{"id": "desk_01", "class": "desk"}],
        }

    def score_response(self, **overrides):
        result = {"B1": 3, "B2": 3, "B3": 3, "B4": 3, "B5": 3}
        result.update(overrides)
        return iter([stream_chunk(json.dumps(result))])

    def test_large_image_is_resized_and_encoded_as_jpeg(self):
        from PIL import Image

        part = gpt_scoring._img_part(self.make_png((200, 100)), max_px=80)
        url = part["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        raw = base64.b64decode(url.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual((80, 40), image.size)

    def test_streaming_joins_chunks_and_uses_small_output_limit(self):
        image = self.make_png()
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        api = fake_client([iter([
            stream_chunk('{"winner":'),
            stream_chunk('"A"}'),
            stream_chunk(usage=usage),
        ])])
        output = io.StringIO()
        with mock.patch.object(gpt_scoring, "_client", api), \
             mock.patch.object(gpt_scoring, "STREAM", True), \
             mock.patch.object(gpt_scoring, "MAX_TOKENS", 512), \
             contextlib.redirect_stdout(output):
            result = gpt_scoring._ask("judge", [image], max_retries=1)

        self.assertEqual({"winner": "A"}, result)
        call = api.completions.calls[0]
        self.assertIs(True, call["stream"])
        self.assertEqual(512, call["max_tokens"])
        self.assertEqual("none", call["reasoning_effort"])
        self.assertEqual({"include_usage": True}, call["stream_options"])
        self.assertIn("[usage] in=100 out=20", output.getvalue())

    def test_missing_stream_usage_is_logged_as_none(self):
        image = self.make_png()
        api = fake_client([iter([stream_chunk('{"winner":"A"}')])])
        output = io.StringIO()
        with mock.patch.object(gpt_scoring, "_client", api), \
             mock.patch.object(gpt_scoring, "STREAM", True), \
             contextlib.redirect_stdout(output):
            result = gpt_scoring._ask("judge", [image], max_retries=1)

        self.assertEqual({"winner": "A"}, result)
        self.assertIn("[usage] in=None out=None", output.getvalue())

    def test_524_retries_with_exponential_backoff(self):
        image = self.make_png()
        api = fake_client([
            HttpError(524),
            iter([stream_chunk('{"winner":"B"}')]),
        ])
        sleeps = []
        with mock.patch.object(gpt_scoring, "_client", api), \
             mock.patch.object(gpt_scoring, "STREAM", True), \
             mock.patch.object(gpt_scoring, "RETRY_DELAY_SECONDS", 2):
            result = gpt_scoring._ask("judge", [image], sleep=sleeps.append)

        self.assertEqual({"winner": "B"}, result)
        self.assertEqual([2], sleeps)
        self.assertEqual(2, len(api.completions.calls))

    def test_client_error_is_not_retried(self):
        image = self.make_png()
        api = fake_client([HttpError(400)])
        sleeps = []
        with mock.patch.object(gpt_scoring, "_client", api), \
             mock.patch.object(gpt_scoring, "STREAM", True):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                gpt_scoring._ask("judge", [image], sleep=sleeps.append)

        self.assertEqual([], sleeps)
        self.assertEqual(1, len(api.completions.calls))

    def test_out_of_range_score_retries_then_accepts_valid_response(self):
        image = self.make_png()
        api = fake_client([
            self.score_response(B3=10),
            self.score_response(B3=5),
        ])
        sleeps = []
        with mock.patch.object(gpt_scoring, "_client", api), \
             mock.patch.object(gpt_scoring, "STREAM", True), \
             mock.patch.object(gpt_scoring, "RETRY_DELAY_SECONDS", 2):
            result = gpt_scoring.score_scene(
                [image], self.score_scene(), max_retries=2,
                sleep=sleeps.append)

        self.assertEqual(5, result["B3"])
        self.assertEqual(3.4, result["mean"])
        self.assertEqual([2], sleeps)
        self.assertEqual(2, len(api.completions.calls))

    def test_all_invalid_scores_return_none_after_retries(self):
        image = self.make_png()
        api = fake_client([
            self.score_response(B3=10),
            self.score_response(B1=0),
            self.score_response(B5="5"),
        ])
        sleeps = []
        with mock.patch.object(gpt_scoring, "_client", api), \
             mock.patch.object(gpt_scoring, "STREAM", True), \
             mock.patch.object(gpt_scoring, "RETRY_DELAY_SECONDS", 2):
            result = gpt_scoring.score_scene(
                [image], self.score_scene(), max_retries=3,
                sleep=sleeps.append)

        self.assertIsNone(result)
        self.assertEqual([2, 4], sleeps)
        self.assertEqual(3, len(api.completions.calls))

    def test_integral_float_scores_are_normalized_to_int(self):
        result = gpt_scoring._validate_scores({
            "B1": 1.0, "B2": 2.0, "B3": 3.0, "B4": 4.0, "B5": 5.0})
        self.assertEqual([1, 2, 3, 4, 5],
                         [result[f"B{i}"] for i in range(1, 6)])

    def test_default_output_budget_is_1024(self):
        self.assertEqual(1024, gpt_scoring.MAX_TOKENS)


if __name__ == "__main__":
    unittest.main()
