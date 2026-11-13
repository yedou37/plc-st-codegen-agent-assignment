"""Check the installed CODESYS adapter with a reachable valid and invalid FB."""
import json
from pathlib import Path
from codesys_compile import compile_one

ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'experiments/local_runs/compiler_controls';out.mkdir(parents=True,exist_ok=True)
    prefix='FUNCTION_BLOCK FB_Control\nVAR_OUTPUT\n value : INT;\nEND_VAR\n'
    sources={'valid':prefix+'value := 1;\nEND_FUNCTION_BLOCK\n',
             'invalid':prefix+'value := ;\nEND_FUNCTION_BLOCK\n'}
    results={}
    for name,source in sources.items():
        path=out/(name+'.st');path.write_text(source,encoding='utf-8')
        results[name]=compile_one(path,'CONTROL',out/(name+'.json'))['status']
    results['controls_passed']=results['valid']=='PASS' and results['invalid']=='FAIL'
    (out/'summary.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results))
    return 0 if results['controls_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
