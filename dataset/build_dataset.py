"""Build the annotated PLC benchmark from the supplied question bank."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_ZIP = HERE / "sources" / "题库原始JSON.zip"
OUT = HERE / "tasks.json"

# The public-question property strings are scan-level LTL. Timed PLC behavior
# uses explicit timer-done propositions (e.g. T5s) supplied by the model.
PUBLIC = {
"P01": ("easy", [
"G(phase = CLEAN -> Pump_Motor)", "G(phase = FILL -> Filling_Valve)",
"G(phase = CAP -> Capping_Machine)", "G(phase = PACK -> Packing_Machine)",
"G(finishedPulse & phase = PACKED -> X(phase = IDLE & !Completion_Light))"],
["Idle + bottleSensor↑: enter CLEAN; Pump_Motor=TRUE.", "CLEAN + cleaningConfirmButton↑: enter FILL; pump off and filling valve on.", "Complete each station in order: CAP -> PACK -> PACKED; Completion_Light on.", "PACKED + finishedButton↑: reset to IDLE; all actuators and light off."],
"Confirmation buttons are edge-triggered; a new bottle is accepted only in IDLE; station outputs are mutually exclusive; PACKED means packing confirmation was accepted."),
"P02": ("easy", [
"G(risingBits = value & !prevValue)", "G(fallingBits = prevValue & !value)",
"G(hasChanged <-> value != prevValue)", "G(noOfRisingBits = popcount(risingBits) & noOfFallingBits = popcount(fallingBits))"],
["First invocation with value=0: no edges and counts zero.", "prev=16#0000000F, value=16#00000013: risingBits=16#10; fallingBits=16#0C; counts 1 and 2.", "Same value on consecutive scans: hasChanged=FALSE and both edge masks zero."],
"Previous value initializes to zero, so the first call reports changes relative to zero. Counts use unsigned 32-bit masks."),
"P03": ("easy", [
"G(loLevel >= hiLevel -> error & status = 16#8001 & !hiAlarm & !loAlarm)",
"G(loLevel < hiLevel & hystWindow >= hiLevel-loLevel -> error & status = 16#8002)",
"G((validConfig & Value>hiLevel) -> hiAlarm)", "G((validConfig & Value<loLevel) -> loAlarm)",
"G((validConfig & prevHiAlarm & Value>=hiLevel-hystWindow) -> hiAlarm)",
"G((validConfig & prevLoAlarm & Value<=loLevel+hystWindow) -> loAlarm)"],
["lo=20, hi=80, hyst=5, Value=81: high alarm sets.", "High alarm latched; Value=77: remains on; Value=74: clears.", "lo=80, hi=80: error 16#8001; no alarm output."],
"prevHiAlarm and prevLoAlarm are the stored latch states entering the scan. Invalid configuration does not update those latches. Hysteresis equality keeps the relevant latch set."),
"P04": ("easy", [
"G(!PASTE_E_STOP_NC -> !VFD_RUN & debounceElapsed = 0)",
"G(VFD_RUN -> (PASTE_E_STOP_NC & VISCOSITY_OK & viscosityValid & DebounceTime>T#0s & CycleTime>T#0s))",
"G((VISCOSITY_OK & PASTE_E_STOP_NC & DebounceTime>T#0s & CycleTime>T#0s & debounceElapsed>=DebounceTime) -> viscosityValid)",
"G((!VISCOSITY_OK | !PASTE_E_STOP_NC) -> !viscosityValid)",
"G(VFD_RUN -> PUMP_RUNTIME_ACC = prevPumpRuntime + CycleTime)",
"G(!VFD_RUN -> PUMP_RUNTIME_ACC = prevPumpRuntime)",
"G(PUMP_MAINT_DUE <-> (PUMP_RUNTIME_ACC >= LTIME#500h))"],
["Power-up: VFD_RUN=FALSE, runtime=0, maintenance=FALSE.", "VISCOSITY_OK shorter than DebounceTime: pump remains off.", "After valid debounce with E-stop permissive: pump runs; runtime adds CycleTime; E-stop drop turns it off immediately."],
"Timer uses supplied elapsed scan time. Nonpositive DebounceTime or CycleTime inhibits run. prevPumpRuntime is zero before the first scan and is the previous PUMP_RUNTIME_ACC thereafter."),
"P05": ("easy", [
"G(initActive -> Weld_Soft_Start_Active & !Operator_Alert)",
"G(!Weld_E_Stop_NC -> !Operator_Alert & debounceElapsed = 0)",
"G((!initActive & Weld_E_Stop_NC & debounceElapsed>=DebounceTime & Gap_Exceeded) -> Operator_Alert)",
"G(!Gap_Exceeded -> (!Operator_Alert & debounceElapsed=0))"],
["Boot before 5 s: soft-start/inhibition TRUE and alert FALSE even if gap signal is high.", "After 5 s, continuously high gap reaches DebounceTime: alert TRUE.", "E-stop active or gap drops: alert immediately FALSE and partial debounce clears."],
"Initialization is a one-shot 5 s power-up interval; emergency stop clears the alarm and debounce but does not restart the boot interval."),
"P06": ("easy", [
"G((!DO_LOW | !AERATION_E_STOP_NC) -> !BLOWER_RUN & startElapsed = 0)",
"G(BLOWER_RUN -> DO_LOW & AERATION_E_STOP_NC & startElapsed >= T#5s)",
"G((BLOWER_RUN & !prevBLOWER_RUN) -> AERATION_BLOWER_CYCLE_COUNT = min(prevCount+1, UINT_MAX))",
"G(!(BLOWER_RUN & !prevBLOWER_RUN) -> AERATION_BLOWER_CYCLE_COUNT = prevCount)"],
["Demand true for less than 5 s: blower remains off.", "Demand and permissive stay true for 5 s: blower starts and count increments once.", "Demand drops or E-stop opens: blower stops; renewed demand waits a full 5 s."],
"Start button is not present; count saturates at UINT max rather than wrapping."),
"P07": ("medium", [
"G((stop | !start) -> AND_i(!pumpGroup[i].RunComd))",
"G((mode & start & !stop) -> AND_i(pumpGroup[i].RunComd <-> rank_i <= 3))",
"G((!mode & start & !stop) -> AND_i(pumpGroup[i].RunComd <-> pumpGroup[i].selection))",
"G((mode & start & !stop) -> countRunningPumps = 3)"],
["Manual, start held with pumps 1 through 4 selected: those four run; pump 5 stops.", "Automatic priorities [1,5,3,4,2], start: pumps 2,3,4 run (tie breaks by lower index).", "stop TRUE: all five commands FALSE in either mode."],
"Start is a level-sensitive run request in both modes. Auto mode selects exactly three highest-ranked pumps; rank_i is one-based and ties break by lower array index. AND_i ranges over 1..5; countRunningPumps counts true RunComd fields. Stop has priority."),
"P08": ("medium", [
"G(!channels[i].enable -> X(retVal[i]=0 & outputValue[i]=prevOutputValue[i]))",
"G(measuringMode[i] notin {0,1,2} -> X(retVal[i]=16#8001))",
"G(hiLIM[i] <= loLIM[i] -> X(retVal[i]=16#8002))",
"G(mode=0 & valid -> outputValue = loLIM + (raw-rawMin)*(hiLIM-loLIM)/(rawMax-rawMin))",
"G(mode=1 & valid -> outputValue=raw/10.0)", "G(mode=2 & valid -> outputValue=raw/100.0)"],
["Unipolar raw 0 and 27648 map to loLIM and hiLIM.", "Bipolar raw -27648 maps to loLIM and +27648 maps to hiLIM.", "Disabled channel leaves output unchanged; invalid mode returns 16#8001."],
"Ordinal pairing begins at each array's own lower bound. Invalid mode takes precedence over invalid range; count is contractually in bounds."),
"P09": ("medium", [
"G(reset -> (occupancy=0 & average=0.0 & !windowSizeReached))",
"G(windowSize notin 1..100 -> error & status=16#8200)",
"G((valid & sampleAccepted) -> average = sum(currentWindow)/occupancy)",
"G(valid -> (windowSizeReached <-> occupancy=windowSize))",
"G(cyclicExecution -> (sampleAccepted <-> (valid & !reset)))",
"G(!cyclicExecution -> (sampleAccepted <-> (valid & trigger & !prevTrigger & !reset)))"],
["window=3, samples 1,2,3: average=2; windowSizeReached TRUE.", "Next sample 7: oldest 1 evicted; average=4.", "reset TRUE: average=0 and occupancy resets; invalid window reports 16#8200."],
"Cyclic execution supersedes trigger; reset has priority. valid means windowSize is in 1..100. currentWindow contains the accepted sample and the most recent retained samples; occupancy is its post-scan length."),
"P10": ("medium", [
"G(sensorFault -> !HeaterOutput & !HeaterStatus)",
"G(OverheatProtection -> !HeaterOutput)",
"G(heaterOnElapsed > T#5s -> X(OverheatProtection))",
"G(OverheatProtection & !cooldownElapsed3s -> X(OverheatProtection))",
"G(!sensorFault & !OverheatProtection & TemperatureSensorInput < SetTemperature -> HeaterOutput)"],
["Valid temperature below setpoint: heater on.", "Continuous heater on beyond 5 s: overheat protection on and heater off.", "Sensor below 0 or above 100: heater and status off; protection clears only after 3 s cooldown."],
"A rising setpoint crossing is not required; heating resumes when valid, below setpoint, and cooldown is complete. 'More than 5 s' is strict."),
"P11": ("medium", [
"G(Mode=0 -> !(MotorForward & MotorReverse))",
"G(Mode=0 & ForwardButton & !ReverseButton -> MotorForward)",
"G((Mode=1 & MotorForward) -> (stage=TRAVEL_AB | stage=TRAVEL_BC))",
"G((Mode=1 & stage=AT_B & !ButtonBComplete) -> !MotorForward)",
"G((Mode=1 & SensorC & stage=AT_C) -> !MotorForward)",
"G((Mode=1 & complete & SensorC) -> CompletionLight)",
"G((Mode=1 & !SensorC) -> !CompletionLight)"],
["Manual both buttons TRUE: both motor directions FALSE.", "SensorA and ButtonA completion: automatic conveyor advances toward B.", "At C after ButtonC completion: conveyor stopped and light TRUE; product removal clears light."],
"Automatic progression is A->B->C; button confirmations are rising-edge events; changing mode cancels automatic motion and clears step state."),
"P12": ("medium", [
"G(!THICKNESS_SIGNAL_VALID -> !THICKNESS_ALARM & !alarmHold & noHistoryWrite)",
"G((THICKNESS_SIGNAL_VALID & THICKNESS_FAULT & !prevValidFault) -> (Slab_Fault_Counter = prevSlabCount+1 & Slab_Fault_History[0] = FaultTimestamp))",
"G(THICKNESS_ALARM <-> (THICKNESS_SIGNAL_VALID & (THICKNESS_FAULT | alarmHold)))",
"G((CUTTING_RUN & THICKNESS_SIGNAL_VALID & !THICKNESS_FAULT) -> Slab_Runtime_Accumulator = prevSlabRuntime+CycleTime)",
"G(!(CUTTING_RUN & THICKNESS_SIGNAL_VALID & !THICKNESS_FAULT) -> Slab_Runtime_Accumulator = prevSlabRuntime)"],
["Valid fault rising edge: alarm on, count +1, newest timestamp at index 0.", "Fault clears before 500 ms: alarm remains on until hold timer completes.", "Invalid signal: alarm off, no record/runtime update."],
"prevValidFault is the preceding scan's conjunction of validity and fault; alarmHold is a triggered hold whose elapsed time is below 500 ms. prevSlabCount and prevSlabRuntime are previous-scan values, initialized to zero. CycleTime is positive. History is newest-first and alarm hold clears on invalid input."),
"P13": ("medium", [
"G((!occupied | nightMode) -> !SUPPLY_FAN_RUN & startElapsed=0)",
"G(SUPPLY_FAN_RUN -> occupied & !nightMode & startElapsed>=T#30s)",
"G(mode=0 & occupied -> TEMP_SETPOINT_ADJUST=0)",
"G(mode=0 & !occupied & energySave -> TEMP_SETPOINT_ADJUST=3)",
"G(mode=0 & !occupied & !energySave -> TEMP_SETPOINT_ADJUST=2)",
"G(mode=1 & !occupied -> TEMP_SETPOINT_ADJUST=1)",
"G(mode=2 & !occupied -> TEMP_SETPOINT_ADJUST=4)",
"G(mode=3 -> TEMP_SETPOINT_ADJUST=4)"],
["Occupied in Auto: adjustment 0; fan waits 30 s then runs.", "Unoccupied Auto, energy-save: +3 C; standard: +2 C.", "Night mode: +4 C and fan off regardless of occupancy."],
"Invalid mode 4.. is clamped to safe outputs (fan off, adjustment 0) and reported by internal diagnostic; source interface has no error output."),
"P14": ("medium", [
"G(validIPv4(ipText) -> ipValue=networkByteOrder(ipText))",
"G(!validIPv4(ipText) -> ipValue=0)",
"G(validIPv4(ipText) -> octetCount=4 & allOctetsInRange0to255)"],
["'192.168.1.10' -> 16#C0A8010A.", "'0.0.0.0' -> 0 and is valid.", "'256.1.1.1', '1..2.3', '1.2.3' and '1.2.3.4x' -> 0."],
"Leading zeros are accepted as decimal digits; whitespace and plus/minus signs are rejected; caller provides a bounded string."),
"P15": ("hard", [
"G(!estop -> !valveARun & !valveBRun & !valveCRun & !valveDRun & !mixMotorRun)",
"G((estop & opeMode & prevStep=FILL_A & levelSensor<50) -> (valveARun & !valveBRun))",
"G((estop & opeMode & prevStep=FILL_A & levelSensor>=50) -> (step=FILL_B & !valveARun & valveBRun))",
"G((estop & opeMode & prevStep=FILL_B & levelSensor>=80 & !processMode) -> step=MIX)",
"G((estop & opeMode & prevStep=FILL_B & levelSensor>=80 & processMode) -> step=FILL_C)",
"G((estop & opeMode & prevStep=FILL_C & levelSensor>=100) -> step=MIX)",
"G((estop & opeMode & prevStep=MIX & mixMotorComplete) -> step=DISCHARGE)"],
["E-stop FALSE in any mode: all five outputs off immediately.", "Auto start at level 0: valve A opens; at 50 cm changes to B; at 80 cm closes B.", "Process mode TRUE: fill C to 100 cm, mix until complete, then discharge via D."],
"E-stop is active-low and global. Automatic start is edge-triggered; manual outputs toggle on each button rising edge; one mode is selected at a time."),
"P16": ("hard", [
"G(conveyorLeft -> !conveyorRight)", "G(conveyorRight -> !conveyorLeft)",
"G(moveIssued -> F((targetSensor & !conveyorLeft & !conveyorRight) | sequenceAborted))",
"G(processingStationReached & !completeSignal -> !conveyorLeft & !conveyorRight)",
"G((prevTargetStation=5 & moveInProgress & sensor5) -> (!conveyorLeft & !conveyorRight & done))"],
["Start at station1 with sequence [3,2,5]: conveyor moves toward 3, stops at sensor3.", "At station3, no completion: remain stopped; after station3Complete, route to station2.", "At final station5 sensor: stop; no further sequence read."],
"Sequence entries 2..4 are valid and the final entry is 5. Left means decreasing station number and right means increasing. Invalid lengths inhibit motion. Travel is assumed to receive target sensor feedback unless the sequence is aborted."),
"P17": ("hard", [
"G(queryRecipe & found -> X(recipeQueryResult=matchedRecipe & !error))",
"G(queryRecipe & !found -> X(error & status=16#8001))",
"G(addRecipe & duplicate -> X(error & status=16#8002))",
"G(addRecipe & !duplicate & full -> X(error & status=16#8003))",
"G(deleteRecipe & !found -> X(error & status=16#8004))",
"G(modifyRecipe & !found -> X(error & status=16#8005))",
"G(successfulAdd -> X(databaseUniqueIDs & storedAtLowestFreeIndex))"],
["Query existing ID returns the exact record; query missing ID yields 16#8001.", "Add duplicate returns 16#8002; full database returns 16#8003.", "Delete existing ID clears its slot; modify missing ID returns 16#8005."],
"Operation requests are rising-edge triggered and mutually exclusive; simultaneous requests are rejected as ambiguous (error status 16#80FF). ID 0 is reserved."),
"P18": ("hard", [
"G(reset -> X(elementCount=0 & status=16#0000))",
"G(dequeueEdge & elementCount=0 & !reset -> X(status=16#8001 & item=prevItem))",
"G(enqueueEdge & elementCount=capacity & !reset -> X(status=16#8002 & item=prevItem))",
"G(successfulDequeue -> X(item=oldestElement & elementCount=prevCount-1))",
"G(successfulEnqueue -> X(elementCount=prevCount+1))",
"G(elementCount in 0..capacity)"],
["Empty buffer + dequeue↑: status 16#8001, item unchanged.", "Enqueue values 11,22 then dequeue↑: item=11; count=1.", "Fill capacity then enqueue↑: status 16#8002; buffer and item unchanged."],
"Reset dominates edges; simultaneous enqueue/dequeue is forbidden by caller contract; edge histories persist across reset."),
"P19": ("hard", [
"G(!EmergencyStop -> allMotionOutputsOff)",
"G((ManualMode & EmergencyStop) -> manualCommandsMatchPermittedButtons)",
"G(AtMost1Of(MoveDown,MoveUp) & AtMost1Of(MoveLeft,MoveRight) & AtMost1Of(ActivateGrip,ActivateRelease))",
"G((SingleCycleMode & cycleStarted & EmergencyStop) -> F(cycleFinished | !SingleCycleMode | !EmergencyStop))",
"G((ContinuousMode & cycleStarted & EmergencyStop) -> F(cycleRestart | !ContinuousMode | !EmergencyStop))"],
["E-stop FALSE during any command: all six outputs off in that scan.", "Manual DownButton held at DownLimitSwitch: MoveDown stays off.", "Single cycle start: ordered eight operations finish at top-left and stop."],
"Start is edge-triggered. A commanded motion is assumed to receive its position feedback if the mode and permissive remain active. cycleFinished means the final left motion reaches its limit and all six commands are off. In manualCommandsMatchPermittedButtons each command equals its button AND NOT its limit AND NOT the opposite button. Opposing requests suppress both commands."),
"P20": ("hard", [
"G(Mode=0 & ForwardButton & !ReverseButton -> MotorForward & !MotorReverse)",
"G(Mode=0 & ReverseButton & !ForwardButton -> MotorReverse & !MotorForward)",
"G(Mode=0 & ForwardButton & ReverseButton -> !MotorForward & !MotorReverse)",
"G((Mode=1 & stage=WAIT_WASH & !washComplete) -> (!MotorForward & !MotorReverse))",
"G((Mode=1 & acceptedWeight & 100<=weight & weight<=200) -> (500<=firingTemp & firingTemp<=550))",
"G((Mode=1 & acceptedWeight & 100<=weight & weight<=200) -> firingTemp=500+(weight-100)*0.5)",
"G((Mode=1 & acceptedWeight & (weight<100 | weight>200)) -> kick)",
"G((Mode=1 & finishedAtOutput & SensorOutput) -> (!MotorForward & !MotorReverse & CompletionLight))",
"G((Mode=1 & !SensorOutput) -> !CompletionLight)"],
["Manual forward and reverse both pressed: both outputs off.", "Weight 100 -> temp 500; weight 150 -> 525; weight 200 -> 550.", "Weight 99 after weighing: kick on; weight 201 also rejected."],
"Automatic stages advance only after their completion signals. acceptedWeight is the scan in which the active weighing stage accepts weightComplete. finishedAtOutput means the active firing-to-output move has reached the finished-product station. A mode change aborts an in-flight sequence. kick is a one-scan pulse."),
}

SYNTHETIC = json.loads((HERE / "synthetic_tasks.json").read_text(encoding="utf-8"))

def parse_interface(md: str):
    block = md.split("## Interface Definition", 1)[-1]
    rows = []
    for line in block.splitlines():
        if not line.startswith("|") or re.match(r"\|\s*:?-+", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0].lower() not in ("direction", ""):
            rows.append({"direction": cells[0], "name": cells[1].strip("`").replace("<br>", " "), "type": cells[2].strip("`").replace("<br>", " "), "description": cells[3].replace("<br>", "; ")})
    return rows

def parse_synthetic_interface(requirements: str):
    match = re.search(r"Inputs:\s*(.*?)\.\s*Outputs:\s*(.*?)(?:\.\s+[A-Z][a-z]|$)", requirements, flags=re.S)
    if not match:
        raise ValueError("Synthetic task must declare typed Inputs and Outputs")
    rows = []
    for direction, segment in (("Input", match.group(1)), ("Output", match.group(2))):
        for item in segment.split(","):
            parts = item.strip().split()
            if len(parts) < 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[0]):
                raise ValueError(f"Cannot parse {direction.lower()} declaration: {item!r}")
            rows.append({"direction":direction,"name":parts[0],"type":parts[1],
                         "description":f"{direction} variable declared in the task requirements."})
    return rows

def main():
    with zipfile.ZipFile(SOURCE_ZIP) as zf:
        original_name = next(n for n in zf.namelist() if n.lower().endswith(".json"))
        bank = json.loads(zf.read(original_name).decode("utf-8-sig"))
    tasks = []
    counter = 1
    for level in ("easy", "medium", "hard"):
        for item in bank[level]:
            md = item["en"]
            title = re.search(r"^#\s+(.+)", md, re.M).group(1).strip()
            pub_id = f"P{counter:02d}"
            difficulty, specs, tests, assumptions = PUBLIC[pub_id]
            requirements = re.split(r"##\s+Interface Definition", re.split(r"##\s+Requirements", md, 1)[-1], 1)[0].strip()
            tasks.append({"id":pub_id,"origin":"provided_public_bank","difficulty":difficulty,"title":title,
                "requirements":requirements,"interface":parse_interface(md),"source":{"type":"provided dataset","file":"question_bank_original.json","category":level,"original_title":title},
                "adaptation_notes":"Requirement wording and interface are preserved from the supplied JSON. The stated assumption resolves scan timing or tie behavior for a deterministic benchmark; it does not change the core task.",
                "assumptions":assumptions,"ltl_profile":"Scan-level future-time LTL; timer completion and state predicates are explicitly named atoms. See docs/DATASET_SPEC.md.","specs":[{"id":f"{pub_id}-L{i+1}","formula":s} for i,s in enumerate(specs)],
                "test_cases":[{"id":f"{pub_id}-T{i+1}","scenario":t} for i,t in enumerate(tests)]})
            counter += 1
    for item in SYNTHETIC:
        tasks.append({"id":item["id"],"origin":"self_built_synthetic","difficulty":item["difficulty"],"title":item["title"],
            "requirements":item["requirements"],"interface":parse_synthetic_interface(item["requirements"]),"source":{"type":"originally synthesized for this assignment","record":"No external source text copied; see docs/DATASET_SPEC.md for generation, review, and rationale."},
            "adaptation_notes":"Original synthetic task. State and timing assumptions are made explicit so the test oracle is deterministic.","assumptions":item["assumptions"],
            "ltl_profile":"Scan-level future-time LTL; timer completion and state predicates are explicitly named atoms. See docs/DATASET_SPEC.md.",
            "specs":[{"id":f"{item['id']}-L{i+1}","formula":s} for i,s in enumerate(item["specs"])],
            "test_cases":[{"id":f"{item['id']}-T{i+1}","scenario":t} for i,t in enumerate(item["tests"])]})
    result = {"benchmark":"PLC-ST-Agent-Benchmark","version":"1.1","scan_semantics":"Each trace position pairs sampled inputs with the outputs and state produced by that scan. prev variables refer to the preceding scan. X denotes the next trace position.","spec_profile":"Future-time LTL with typed comparisons and named timer/state predicates. Backend verification requires explicit predicate bindings and macro expansion.","task_count":len(tasks),"public_count":counter-1,"self_built_count":len(SYNTHETIC),"tasks":tasks}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (HERE/"question_bank_original.json").open("w",encoding="utf-8") as f: json.dump(bank,f,ensure_ascii=False,indent=2); f.write("\n")
    print(f"wrote {OUT}: {len(tasks)} tasks ({counter-1} public, {len(SYNTHETIC)} self-built)")

if __name__ == "__main__": main()
