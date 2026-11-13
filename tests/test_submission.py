import json
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"tools"))

from src.static_check import check_source, extract_st
from src.adapters import chat_completion
from dmxapi_metered_proxy import BudgetLedger, _collect_usage
from run_st_tests import normalize_strucpp_source
from codesys_linked import prepare, SourceError

class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/"dataset"/"tasks.json").read_text(encoding="utf-8"))

    def test_all_twenty_public_and_ten_synthetic_tasks_exist(self):
        tasks=self.data["tasks"]
        self.assertEqual(len(tasks),30)
        self.assertEqual(len({t["id"] for t in tasks}),30)
        self.assertEqual(sum(t["origin"]=="provided_public_bank" for t in tasks),20)
        self.assertEqual(sum(t["origin"]=="self_built_synthetic" for t in tasks),10)

    def test_each_task_has_formal_properties_and_test_scenarios(self):
        for task in self.data["tasks"]:
            with self.subTest(task=task["id"]):
                self.assertGreaterEqual(len(task["specs"]),2)
                self.assertGreaterEqual(len(task["test_cases"]),2)
                self.assertTrue(all(x["formula"].strip() for x in task["specs"]))
                self.assertTrue(all(x["scenario"].strip() for x in task["test_cases"]))

    def test_each_task_has_a_typed_input_output_interface(self):
        for task in self.data["tasks"]:
            with self.subTest(task=task["id"]):
                interface=task["interface"]
                self.assertTrue(interface)
                self.assertEqual(len({x["name"] for x in interface}),len(interface))
                self.assertTrue(all(x["direction"].strip() for x in interface))
                self.assertTrue(all(x["name"].strip() and x["type"].strip() for x in interface))
                self.assertTrue(any(x["direction"].lower().startswith("input") for x in interface))
                self.assertTrue(any("output" in x["direction"].lower() for x in interface))
                if task["origin"]=="self_built_synthetic":
                    self.assertTrue(all(x["direction"] in ("Input","Output") for x in interface))

    def test_synthetic_tasks_have_provenance(self):
        for task in self.data["tasks"]:
            if task["origin"]=="self_built_synthetic":
                self.assertIn("originally synthesized",task["source"]["type"])
                self.assertTrue(task["assumptions"])

class SourceAdapterTests(unittest.TestCase):
    def test_compile_harness_calls_each_unit_and_binds_open_arrays(self):
        source = ("FUNCTION_BLOCK Candidate\nVAR_IN_OUT\n values : ARRAY[*] OF DINT;\n"
                  "END_VAR\n values[1] := Helper(1);\nEND_FUNCTION_BLOCK\n"
                  "FUNCTION Helper : DINT\nVAR_INPUT\n x : DINT;\nEND_VAR\n"
                  " Helper := x;\nEND_FUNCTION\n")
        job = prepare(source, "manual")
        self.assertEqual([u["name"] for u in job["units"]], ["Candidate", "Helper"])
        self.assertIn("ARRAY[1..5] OF DINT", job["declaration"])
        self.assertEqual(job["calls"], [
            "AuditHarnessInstance0(values := AuditHarnessArg0_0);",
            "AuditHarnessInstance1 := Helper(x := AuditHarnessArg1_0);",
        ])

    def test_compile_harness_rejects_truncated_and_extra_source(self):
        valid = "PROGRAM Candidate\nVAR\n x : INT;\nEND_VAR\nx := 1;\nEND_PROGRAM\n"
        for source in (valid.removesuffix("END_PROGRAM\n"), valid + "Unexpected text",
                       valid.replace("x := 1;", "(* no implementation *)")):
            with self.subTest(source=source), self.assertRaises(SourceError):
                prepare(source, "manual")

    def test_static_precheck_is_not_compiler(self):
        good="FUNCTION_BLOCK FB_Test VAR x: BOOL; END_VAR IF x THEN x := FALSE; END_IF END_FUNCTION_BLOCK"
        bad="FUNCTION_BLOCK FB_Test VAR x: BOOL; END_FUNCTION_BLOCK"
        self.assertEqual(check_source(good),[])
        self.assertTrue(check_source(bad))

    def test_extract_st_fence(self):
        self.assertEqual(extract_st("```st\nPROGRAM P\nEND_PROGRAM\n```"),"PROGRAM P\nEND_PROGRAM")

    def test_strucpp_normalizes_the_known_equivalent_p02_bit_mask_idiom(self):
        source=("IF ((risingBits SHR i) AND 16#00000001) <> 16#00000000 THEN\n"
                "END_IF;\n")
        normalized, changes=normalize_strucpp_source(source)
        self.assertEqual(changes[0]["replacements"],1)
        self.assertIn("IF (risingBits AND SHL(DWORD#1, i)) <> DWORD#0 THEN",normalized)

    def test_dmxapi_cost_parsing(self):
        out={}
        _collect_usage({"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19,"cost":"¥0.000620"}},out)
        self.assertEqual(out["prompt_tokens"],12)
        self.assertAlmostEqual(out["cost_cny"],0.000620)

    def test_chat_completion_sends_model_specific_params_and_tracks_empty_answer_metadata(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({"id":"probe","choices":[{"finish_reason":"length",
                    "message":{"role":"assistant","content":"","reasoning_content":"private reasoning"}}],
                    "usage":{"prompt_tokens":5,"completion_tokens":8,
                             "completion_tokens_details":{"reasoning_tokens":8}}}).encode()

        cfg={"model_id":"fake-model","base_url":"https://example.invalid/v1",
             "api_key_env":"TEST_DMX_KEY","max_tokens":8,
             "request_params":{"thinking":{"type":"disabled"}}}
        with patch.dict(os.environ,{"TEST_DMX_KEY":"test-secret"}), \
             patch("src.adapters.urllib.request.urlopen",return_value=Response()) as urlopen:
            result=chat_completion([{"role":"user","content":"probe"}],cfg)

        sent=json.loads(urlopen.call_args.args[0].data.decode())
        self.assertEqual(sent["thinking"],{"type":"disabled"})
        self.assertEqual(result["content"],"")
        self.assertEqual(result["response_meta"],{
            "finish_reason":"length","reasoning_chars":17,"reasoning_tokens":8})

    def test_budget_ledger_reserves_each_request_and_fails_closed(self):
        ledger=BudgetLedger(0.20,0.15,768)
        self.assertTrue(ledger.reserve())
        self.assertAlmostEqual(ledger.settle(0.04),0.04)
        self.assertTrue(ledger.reserve())
        self.assertAlmostEqual(ledger.settle(None),0.15)
        self.assertFalse(ledger.reserve())

if __name__=="__main__": unittest.main()
