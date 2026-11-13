# CODESYS linked compile review

The review reran the 120 archived final source files on CODESYS V3.5 SP22 Patch 4 with Control Win V3 x64 3.5.22.40. No model requests were made. All 120 archived source hashes match the review records.

| Strategy | Model | PASS | CODESYS FAIL | Incomplete source |
|---|---|---:|---:|---:|
| Pi single generation with tools disabled | GPT-6.1 Sol | 18 | 0 | 12 |
| Custom harness with up to two repairs | GPT-6.1 Sol | 16 | 0 | 14 |
| Pi single generation with tools disabled | DeepSeek V4.1 Flash | 9 | 2 | 19 |
| Custom harness with up to two repairs | DeepSeek V4.1 Flash | 9 | 1 | 20 |
| Total | | 52 | 3 | 65 |

The intake check requires a matching end marker for every submitted POU and rejects unfinished comments and empty implementations. This is the benchmark's complete-source requirement. Of the 120 outputs, 55 reached CODESYS. The harness called all candidate POUs from a scheduled program, supplied concrete storage for reference arguments, and required a nonempty boot application and compiled signatures. A valid function block passed and the same block with an undeclared identifier produced a compiler error. The generated offline applications were never downloaded.

Of the 90 historical PASS records, 44 did not pass this review. Of the 30 historical FAIL records, six passed. The 65 intake rejections comprise 55 missing POU end markers and 10 unterminated block comments. These are observations about the archived text. The original 768-token cap is a plausible contributor, but archived usage for several cells aggregates multiple calls, so the cause cannot be assigned to every file.

The results describe two specific generation strategies with unequal tool and repair budgets. The recheck evaluates existing outputs generated with the previous specifications. Dataset v1.1 corrects the specification and oracle issues for future generation and testing. Runtime and formal verification evidence retains its original scope.

- [Summary](summary.json)
- [Per-candidate results](results.csv)
- [Calls, signatures and compiler diagnostics](diagnostics.jsonl)
- [CODESYS ScriptApplication documentation](https://content.helpme-codesys.com/en/ScriptingEngine/ScriptApplication.html)
- [CODESYS compiled POU signature API](https://content.helpme-codesys.com/en/ScriptingEngine/ScriptObject.html#get_signature_crc)
