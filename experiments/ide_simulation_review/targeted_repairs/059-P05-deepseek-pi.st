FUNCTION_BLOCK FB_WeldGapAlarm
VAR_INPUT
    Gap_Exceeded     : BOOL;  (* TRUE: scanner detects gap > 1.5 mm *)
    Weld_E_Stop_NC   : BOOL;  (* TRUE: e-stop inactive; FALSE: e-stop active *)
    DebounceTime     : TIME;  (* positive gap-signal debounce duration *)
END_VAR

VAR_OUTPUT
    Operator_Alert        : BOOL;  (* audible/visual alarm command *)
    Weld_Soft_Start_Active: BOOL;  (* power-up monitoring inhibition *)
END_VAR

VAR
    InitTimer        : TON;   (* one-shot 5 s power-up inhibition *)
    DebounceTimer    : TON;   (* gap-signal debounce *)
    InitActive       : BOOL;  (* TRUE while power-up inhibition runs *)
    fbFirstScanDone  : BOOL;  (* ensures InitTimer is only ever started once *)
END_VAR

(* ------------------------------------------------------------------ *)
(* One-shot 5 s power-up initialization timer                          *)
(* Started exactly once; e-stop does NOT restart it (assumption).      *)
(* ------------------------------------------------------------------ *)
InitTimer(IN := NOT fbFirstScanDone, PT := T#5s);
IF NOT fbFirstScanDone AND NOT InitTimer.Q THEN
    (* keep it running; once Q reached, latch first-scan-done below *)
END_IF;
fbFirstScanDone := fbFirstScanDone OR InitTimer.Q;

InitActive := NOT fbFirstScanDone;

(* ------------------------------------------------------------------ *)
(* Debounce timer: accumulates only during normal monitoring,          *)
(* i.e. NOT during initialization and NOT during an active e-stop.     *)
(* ------------------------------------------------------------------ *)
DebounceTimer(
    IN := NOT InitActive
          AND Weld_E_Stop_NC
          AND Gap_Exceeded
          AND DebounceTime > T#0s,
    PT := DebounceTime
);

(* ------------------------------------------------------------------ *)
(* Outputs                                                            *)
(* ------------------------------------------------------------------ *)

(* Emergency stop has highest priority: force alert FALSE, clear debounce *)
IF NOT Weld_E_Stop_NC THEN
    Operator_Alert         := FALSE;
    Weld_Soft_Start_Active := InitActive;
    DebounceTimer(IN := FALSE, PT := DebounceTime);  (* explicit reset of timing *)
    (* NOTE: per requirement 4 e-stop takes priority over initialization,
       so soft-start is also forced FALSE while e-stop is active. *)
ELSE
    (* Normal operation *)
    IF InitActive THEN
        (* Power-up inhibition: alert FALSE, soft-start TRUE, no debounce accumulation *)
        Operator_Alert         := FALSE;
        Weld_Soft_Start_Active := TRUE;
    ELSE
        (* Normal monitoring *)
        Weld_Soft_Start_Active := FALSE;

        IF NOT Gap_Exceeded THEN
            (* Gap cleared: immediate alarm off and debounce reset *)
            Operator_Alert := FALSE;
            DebounceTimer(IN := FALSE, PT := DebounceTime);
        ELSE
            (* Gap high: alert only once debounce has elapsed *)
            IF DebounceTimer.Q THEN
                Operator_Alert := TRUE;
            ELSE
                Operator_Alert := FALSE;
            END_IF;
        END_IF;
    END_IF;
END_IF;

END_FUNCTION_BLOCK