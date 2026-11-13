import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from src.compiler import compile_st
from codesys_invocation import source_pous, compile_caller, SourceSyntaxError, UnsupportedBinding
from codesys_compile_posthoc import split_pou, script_source, compile_one
from run_codesys_runtime_suite import build_driver
import build_runtime_suites


class CompilerStatusTests(unittest.TestCase):
    def test_nested_status_survives_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Path(directory)/'config.json'
            cfg.write_text(json.dumps({'compiler':{'command':['fake']}}))
            for status in ['FAIL', 'TIMEOUT', 'UNAVAILABLE', 'NOT_CONFIGURED']:
                with self.subTest(status=status), patch('src.compiler.subprocess.run', return_value=
                        subprocess.CompletedProcess([], 1, json.dumps({'status':status}), '')):
                    self.assertEqual(compile_st(Path(directory)/'code.st','X',cfg)['status'],status)

    def test_zero_exit_without_structured_success_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Path(directory)/'config.json';cfg.write_text(json.dumps({'compiler':{'command':['fake']}}))
            for output in ['', '{}', '{"status":"UNKNOWN"}']:
                with self.subTest(output=output), patch('src.compiler.subprocess.run',return_value=
                        subprocess.CompletedProcess([],0,output,'')):
                    self.assertEqual(compile_st(Path(directory)/'code.st','X',cfg)['status'],'UNAVAILABLE')
            with patch('src.compiler.subprocess.run',return_value=subprocess.CompletedProcess([],0,'{"status":"PASS"}','')):
                self.assertEqual(compile_st(Path(directory)/'code.st','X',cfg)['status'],'PASS')


class ReachabilityTests(unittest.TestCase):
    SOURCE = '''FUNCTION_BLOCK FB_Test
VAR_IN_OUT
    values : ARRAY[*] OF INT;
END_VAR
VAR_INPUT
    enabled : BOOL;
END_VAR
values[LOWER_BOUND(values, 1)] := 1;
END_FUNCTION_BLOCK
FUNCTION F_Test : INT
VAR_INPUT
    x, y : INT;
END_VAR
F_Test := x + y;
END_FUNCTION
PROGRAM P_Test
VAR_IN_OUT
    count : INT;
END_VAR
count := count + 1;
END_PROGRAM'''

    def test_every_kind_has_reachable_call_and_inout_storage(self):
        pous=source_pous(self.SOURCE,split_pou);caller=compile_caller(pous)
        self.assertEqual(caller['referenced_pous'],['FB_Test','F_Test','P_Test'])
        self.assertIn('instance_0 : FB_Test;',caller['declaration'])
        self.assertIn('arg_0_0 : ARRAY[0..1] OF INT;',caller['declaration'])
        self.assertIn('instance_0(values := arg_0_0, enabled := arg_0_1);',caller['implementation'])
        self.assertIn('result_1 := F_Test(x := arg_1_0, y := arg_1_1);',caller['implementation'])
        self.assertIn('P_Test(count := arg_2_0);',caller['implementation'])
        self.assertIn('ARRAY[*]',pous[0]['declaration'])

    def test_script_attaches_caller_and_imports_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'code.st';p.write_text(self.SOURCE)
            script=script_source(p,p.with_suffix('.project'),p.with_suffix('.json'),p.with_suffix('.log'),[])
            compile(script,'codesys_script','exec')
            self.assertIn('task.pous.add(CALLER["name"])',script)
            self.assertIn('runner.textual_implementation.replace(CALLER["implementation"])',script)
            self.assertIn('app.get_library_manager().add_library',script)
            self.assertIn('app.rebuild()',script)

    def test_archived_truncated_p11_cannot_return_pass(self):
        source=ROOT/'st/runs/self/deepseek/P11_attempt1.st'
        with tempfile.TemporaryDirectory() as directory, patch('codesys_compile_posthoc.find_codesys') as ide:
            result=compile_one(source,'P11',Path(directory)/'result.json')
            self.assertEqual(result['status'],'FAIL')
            self.assertEqual(result['stage'],'source_parse')
            ide.assert_not_called()

    def test_variant_requires_explicit_fixture(self):
        src='FUNCTION_BLOCK FB\nVAR_IN_OUT\n v : VARIANT;\nEND_VAR\nEND_FUNCTION_BLOCK'
        with self.assertRaises(UnsupportedBinding):compile_caller(source_pous(src,split_pou))


class OracleTests(unittest.TestCase):
    def test_current_dataset_keeps_historical_snapshot(self):
        old=json.loads((ROOT/'dataset/archive/tasks_v1.json').read_text(encoding='utf-8'))
        new=json.loads((ROOT/'dataset/tasks.json').read_text(encoding='utf-8'))
        old_specs={s['id']:s['formula'] for t in old['tasks'] for s in t['specs']}
        new_specs={s['id']:s['formula'] for t in new['tasks'] for s in t['specs']}
        self.assertEqual({k for k in new_specs if new_specs[k]!=old_specs[k]},{'P04-L4','P07-L4'})
        self.assertIn('pre.PUMP_RUNTIME_ACC',new_specs['P04-L4'])
        self.assertEqual(new_specs['P07-L4'],'G(mode -> AtMost3(pumpGroup[*].RunComd))')

    def test_p07_start_and_p01_optional_expectations(self):
        self.assertTrue(build_runtime_suites.V['P07']['cases'][1]['steps'][0]['set']['start'])
        step=build_runtime_suites.V['P01']['cases'][1]['steps'][0]
        self.assertEqual(step['expect'],{'Filling_Valve':True})
        self.assertEqual(step['expect_assumption'],{'Pump_Motor':False})

    def test_accumulator_checked_every_scan_and_failure_latched(self):
        suite=build_runtime_suites.V['P04']
        driver,assertions=build_driver('FB_Test',suite,[{'declaration':'FUNCTION_BLOCK FB_Test\nVAR_OUTPUT\nPUMP_RUNTIME_ACC : LTIME;\nEND_VAR'}])
        self.assertLess(driver.index('runtime_before := dut.PUMP_RUNTIME_ACC;'),driver.index('dut();'))
        self.assertIn('scan_c1_s1_a1 := scan_c1_s1_a1 AND',driver)
        self.assertIn('scan_c1_s1_a1 : BOOL := TRUE;',driver)
        self.assertTrue(any(a['path']=='scan invariant' and a['expected'] is True for a in assertions))


if __name__ == '__main__':unittest.main()
