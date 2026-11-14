"""Materialize hand-authored runtime vectors from the dataset scenario IDs."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/structured_text/runtime_suites"


def a(values=None, expect=None, cycles=1, after_ms=None):
    item = {"set": values or {}, "cycles": cycles}
    if after_ms is not None:
        item["after_ms"] = after_ms
    if expect:
        item["expect"] = expect
    return item


def c(task, *steps):
    return {"id": task, "steps": list(steps)}


V = {}
V["P01"] = {"task_id":"P01", "cases":[
    c("P01-T1", a({"bottleSensor":True}, {"Pump_Motor":True})),
    c("P01-T2", a({"bottleSensor":False,"cleaningConfirmButton":True}, {"Pump_Motor":False,"Filling_Valve":True})),
    c("P01-T3", a({"cleaningConfirmButton":False,"fillingConfirmButton":True}),
      a({"fillingConfirmButton":False,"cappingConfirmButton":True}),
      a({"cappingConfirmButton":False,"packingConfirmButton":True}, {"Completion_Light":True})),
    c("P01-T4", a({"packingConfirmButton":False,"finishedButton":True},
                    {"Pump_Motor":False,"Filling_Valve":False,"Capping_Machine":False,
                     "Packing_Machine":False,"Completion_Light":False}))
]}
V["P02"] = {"task_id":"P02", "cases":[
    c("P02-T1", a({"value":0}, {"hasChanged":False,"noOfRisingBits":0,"noOfFallingBits":0})),
    c("P02-T2", a({"value":15}), a({"value":19}, {"risingBits":16,"fallingBits":12,
                                             "noOfRisingBits":1,"noOfFallingBits":2})),
    c("P02-T3", a({"value":21}), a({"value":21}, {"hasChanged":False,"risingBits":0,"fallingBits":0}))
]}
V["P03"] = {"task_id":"P03", "cases":[
    c("P03-T1", a({"loLevel":20.0,"hiLevel":80.0,"hystWindow":5.0,"Value":81.0}, {"hiAlarm":True})),
    c("P03-T2", a({"Value":77.0}, {"hiAlarm":True}), a({"Value":74.0}, {"hiAlarm":False})),
    c("P03-T3", a({"loLevel":80.0,"hiLevel":80.0,"hystWindow":5.0,"Value":80.0},
                    {"error":True,"status":32769,"hiAlarm":False,"loAlarm":False}))
]}
V["P04"] = {"task_id":"P04", "cases":[
    c("P04-T1", a({"VISCOSITY_OK":False,"PASTE_E_STOP_NC":True,"DebounceTime":"T#100ms","CycleTime":"T#50ms"},
                   {"VFD_RUN":False,"PUMP_RUNTIME_ACC":"LTIME#0ns","PUMP_MAINT_DUE":False})),
    c("P04-T2", a({"VISCOSITY_OK":True}, {"VFD_RUN":False}, cycles=1)),
    c("P04-T3", a({"VISCOSITY_OK":False}, {"VFD_RUN":False,"PUMP_RUNTIME_ACC":"LTIME#0ns"}),
      a({"VISCOSITY_OK":True}, {"VFD_RUN":False,"PUMP_RUNTIME_ACC":"LTIME#0ns"}),
      a({}, {"VFD_RUN":True,"PUMP_RUNTIME_ACC":"LTIME#50ms"}),
      a({}, {"VFD_RUN":True,"PUMP_RUNTIME_ACC":"LTIME#100ms"}),
      a({"PASTE_E_STOP_NC":False}, {"VFD_RUN":False,"PUMP_RUNTIME_ACC":"LTIME#100ms"}))
]}
V["P05"] = {"task_id":"P05", "cases":[
    c("P05-T1", a({"Gap_Exceeded":True,"Weld_E_Stop_NC":True,"DebounceTime":"T#100ms"},
                   {"Weld_Soft_Start_Active":True,"Operator_Alert":False}, cycles=20)),
    c("P05-T2", a({"Gap_Exceeded":True}, {"Weld_Soft_Start_Active":False,"Operator_Alert":True}, cycles=100)),
    c("P05-T3", a({"Weld_E_Stop_NC":False}, {"Operator_Alert":False}),
      a({"Weld_E_Stop_NC":True,"Gap_Exceeded":False}, {"Operator_Alert":False}))
]}
V["P06"] = {"task_id":"P06", "cases":[
    c("P06-T1", a({"DO_LOW":True,"AERATION_E_STOP_NC":True}, {"BLOWER_RUN":False}, cycles=40),
      a({"DO_LOW":False}, {"BLOWER_RUN":False})),
    c("P06-T2", a({"DO_LOW":True,"AERATION_E_STOP_NC":True},
                   {"BLOWER_RUN":True,"AERATION_BLOWER_CYCLE_COUNT":1}, cycles=105)),
    c("P06-T3", a({"DO_LOW":False}, {"BLOWER_RUN":False}),
      a({"DO_LOW":True,"AERATION_E_STOP_NC":False}, {"BLOWER_RUN":False}),
      a({"AERATION_E_STOP_NC":True}, {"BLOWER_RUN":False}, cycles=1))
]}
V["P07"] = {"task_id":"P07", "declarations":["pumpGroup : ARRAY[1..5] OF ST_Pump"],
    "call":"dut(pumpGroup := pumpGroup);", "cases":[
    c("P07-T1", a({"mode":False,"start":True,"@pumpGroup[1].selection":True,"@pumpGroup[2].selection":True,
                    "@pumpGroup[3].selection":True,"@pumpGroup[4].selection":True,"@pumpGroup[5].selection":False},
                   {f"@pumpGroup[{i}].RunComd":i<5 for i in range(1, 6)})),
    c("P07-T2", a({"start":True,"mode":True,"@pumpGroup[1].priority":1,"@pumpGroup[2].priority":5,
                    "@pumpGroup[3].priority":3,"@pumpGroup[4].priority":4,"@pumpGroup[5].priority":2},
                   {f"@pumpGroup[{i}].RunComd":i in (2, 3, 4) for i in range(1, 6)})),
    c("P07-T3", a({"stop":True}, {"@pumpGroup[1].RunComd":False,"@pumpGroup[2].RunComd":False,
                                   "@pumpGroup[3].RunComd":False,"@pumpGroup[4].RunComd":False,"@pumpGroup[5].RunComd":False}))
]}
V["P08"] = {"task_id":"P08", "declarations":[
    "analogValues : ARRAY[0..1] OF INT", "channels : ARRAY[0..1] OF ST_AnalogChannel"],
    "call":"dut(analogValues := analogValues, channels := channels);", "cases":[
    c("P08-T1", a({"count":2,"@analogValues[0]":0,"@analogValues[1]":27648,
                    "@channels[0].enable":True,"@channels[0].measuringMode":0,"@channels[0].bipolar":False,
                    "@channels[0].loLIM":0.0,"@channels[0].hiLIM":100.0,
                    "@channels[1].enable":True,"@channels[1].measuringMode":0,"@channels[1].bipolar":False,
                    "@channels[1].loLIM":0.0,"@channels[1].hiLIM":100.0},
                   {"@channels[0].outputValue":0.0,"@channels[1].outputValue":100.0})),
    c("P08-T2", a({"count":2,"@analogValues[0]":-27648,"@analogValues[1]":27648,
                    "@channels[0].enable":True,"@channels[0].measuringMode":0,"@channels[0].bipolar":True,
                    "@channels[0].loLIM":0.0,"@channels[0].hiLIM":100.0,
                    "@channels[1].enable":True,"@channels[1].measuringMode":0,"@channels[1].bipolar":True,
                    "@channels[1].loLIM":0.0,"@channels[1].hiLIM":100.0},
                   {"@channels[0].outputValue":0.0,"@channels[1].outputValue":100.0})),
    c("P08-T3", a({"count":2,"@channels[0].enable":False,"@channels[0].outputValue":42.0,
                    "@channels[0].retVal":0,"@channels[1].enable":True,"@channels[1].measuringMode":9,
                    "@channels[1].retVal":0}, {"@channels[0].outputValue":42.0,"@channels[1].retVal":32769}))
]}
V["P09"] = {"task_id":"P09", "cases":[
    c("P09-T1", a({"cyclicExecution":True,"trigger":False,"windowSize":3,"value":1.0,"reset":False}),
      a({"value":2.0}), a({"value":3.0}, {"average":2.0,"windowSizeReached":True})),
    c("P09-T2", a({"value":7.0}, {"average":4.0})),
    c("P09-T3", a({"reset":True}, {"average":0.0,"windowSizeReached":False}),
      a({"reset":False,"windowSize":0}, {"error":True,"status":33280}))
]}
V["P10"] = {"task_id":"P10", "cases":[
    c("P10-T1", a({"TemperatureSensorInput":20.0,"SetTemperature":30.0}, {"HeaterOutput":True})),
    c("P10-T2", a({"TemperatureSensorInput":20.0,"SetTemperature":30.0},
                   {"OverheatProtection":True,"HeaterOutput":False}, cycles=120)),
    c("P10-T3", a({"TemperatureSensorInput":-1.0}, {"HeaterOutput":False}),
      a({"TemperatureSensorInput":20.0}, {"OverheatProtection":False}, cycles=60))
]}
V["P11"] = {"task_id":"P11", "cases":[
    c("P11-T1", a({"Mode":False,"ForwardButton":True,"ReverseButton":True}, {"MotorForward":False,"MotorReverse":False})),
    c("P11-T2", a({"Mode":True,"SensorA":True,"ButtonA":True}, {"MotorForward":True,"MotorReverse":False})),
    c("P11-T3", a({"SensorA":False,"SensorB":False,"SensorC":True,"ButtonA":False,"ButtonC":True},
                   {"MotorForward":False,"MotorReverse":False,"CompletionLight":True}),
      a({"SensorC":False,"ButtonC":False}, {"CompletionLight":False}))
]}
V["P12"] = {"task_id":"P12", "cases":[
    c("P12-T1", a({"THICKNESS_FAULT":True,"THICKNESS_SIGNAL_VALID":True,"CUTTING_RUN":True,
                    "FaultTimestamp":123,"CycleTime":"T#50ms"},
                   {"THICKNESS_ALARM":True,"Slab_Fault_Counter":1,"Slab_Fault_History[0]":123})),
    c("P12-T2", a({"THICKNESS_FAULT":False}, {"THICKNESS_ALARM":True,"Slab_Runtime_Accumulator":"LTIME#50ms"}),
      a({}, {"THICKNESS_ALARM":True,"Slab_Runtime_Accumulator":"LTIME#400ms"}, cycles=7)),
    c("P12-T3", a({"THICKNESS_SIGNAL_VALID":False,"THICKNESS_FAULT":True},
                   {"THICKNESS_ALARM":False,"Slab_Fault_Counter":1,"Slab_Runtime_Accumulator":"LTIME#400ms"}))
]}
V["P13"] = {"task_id":"P13", "cases":[
    c("P13-T1", a({"OCCUPANCY_DETECTED":True,"ENERGY_SAVING_MODE":False,"HVAC_MODE_SELECTOR":0},
                   {"TEMP_SETPOINT_ADJUST":0,"SUPPLY_FAN_RUN":False}, after_ms=29000),
      a({}, {"SUPPLY_FAN_RUN":True}, after_ms=2000)),
    c("P13-T2", a({"OCCUPANCY_DETECTED":False,"ENERGY_SAVING_MODE":True,"HVAC_MODE_SELECTOR":0},
                   {"TEMP_SETPOINT_ADJUST":3}),
      a({"ENERGY_SAVING_MODE":False}, {"TEMP_SETPOINT_ADJUST":2})),
    c("P13-T3", a({"HVAC_MODE_SELECTOR":3}, {"TEMP_SETPOINT_ADJUST":4,"SUPPLY_FAN_RUN":False}))
]}
V["P14"] = {"task_id":"P14", "cases":[
    c("P14-T1", a({"ipText":"192.168.1.10"}, {"ipValue":3232235786})),
    c("P14-T2", a({"ipText":"0.0.0.0"}, {"ipValue":0})),
    c("P14-T3", a({"ipText":"256.1.1.1"}, {"ipValue":0}),
      a({"ipText":"1..2.3"}, {"ipValue":0}), a({"ipText":"1.2.3"}, {"ipValue":0}),
      a({"ipText":"1.2.3.4x"}, {"ipValue":0}))
]}
V["P15"] = {"task_id":"P15", "cases":[
    c("P15-T1", a({"estop":False,"opeMode":False,"valveAStart":True,"valveBStart":True,
                    "valveCStart":True,"valveDStart":True,"mixMotorStart":True},
                   {"valveARun":False,"valveBRun":False,"valveCRun":False,"valveDRun":False,"mixMotorRun":False})),
    c("P15-T2", a({"estop":True,"opeMode":True,"processMode":False,"autoStart":True,"levelSensor":0}, {"valveARun":True}),
      a({"autoStart":False,"levelSensor":50}, {"valveARun":False,"valveBRun":True}),
      a({"levelSensor":80}, {"valveBRun":False})),
    c("P15-T3", a({"processMode":True,"autoStart":True,"levelSensor":0}),
      a({"autoStart":False,"levelSensor":100}), a({"mixMotorComplete":True}),
      a({"levelSensor":100}, {"valveDRun":True}))
]}
V["P16"] = {"task_id":"P16", "cases":[
    c("P16-T1", a({"processLength":3,"processSequence[1]":3,"processSequence[2]":2,"processSequence[3]":5,
                    "sensor1":True,"station1Start":True}, {"conveyorRight":True})),
    c("P16-T2", a({"station1Start":False,"sensor1":False,"sensor3":True}, {"conveyorRight":False,"conveyorLeft":False}),
      a({"station3Complete":True}, {"conveyorLeft":True})),
    c("P16-T3", a({"station3Complete":False,"sensor3":False,"sensor2":True,"station2Complete":True}),
      a({"station2Complete":False,"sensor2":False,"sensor5":True}, {"conveyorLeft":False,"conveyorRight":False}))
]}
V["P17"] = {"task_id":"P17", "declarations":["recipeDB : ARRAY[1..10] OF ST_Recipe"],
    "call":"dut(recipe := recipeDB);", "cases":[
    c("P17-T1", a({"@recipeDB[1].recipeID":0,"recipeIn.recipeID":101,"recipeIn.ingredientType":1,
                    "recipeIn.ingredientRatio":0.5,"recipeIn.productionTemperature":80.0,"addRecipe":True}),
      a({"addRecipe":False,"queryRecipe":True}, {"recipeQueryResult.recipeID":101,"status":0}),
      a({"queryRecipe":False,"recipeIn.recipeID":999,"queryRecipe":True}, {"status":32769})),
    c("P17-T2", a({"queryRecipe":False,"recipeIn.recipeID":101,"addRecipe":True}, {"status":32770})),
    c("P17-T3", a({"addRecipe":False,"queryRecipe":False,"deleteRecipe":True,"recipeIn.recipeID":101},
                   {"recipeDeleted":True}),
      a({"deleteRecipe":False,"modifyRecipe":True,"recipeIn.recipeID":999}, {"status":32773}))
]}
V["P18"] = {"task_id":"P18", "declarations":["item : DINT", "buffer : ARRAY[0..2] OF DINT"],
    "call":"dut(item := item, buffer := buffer);", "cases":[
    c("P18-T1", a({"@item":77,"dequeue":True}, {"status":32769,"@item":77})),
    c("P18-T2", a({"dequeue":False,"reset":True}),
      a({"reset":False,"@item":11,"enqueue":True}), a({"enqueue":False,"@item":22,"enqueue":True}),
      a({"enqueue":False,"dequeue":True}, {"@item":11,"elementCount":1})),
    c("P18-T3", a({"dequeue":False,"reset":True}),
      a({"reset":False,"@item":11,"enqueue":True}), a({"enqueue":False,"@item":22,"enqueue":True}),
      a({"@item":33,"enqueue":True}), a({"enqueue":False,"@item":44,"enqueue":True}, {"status":32770,"elementCount":3}))
]}
V["P19"] = {"task_id":"P19", "cases":[
    c("P19-T1", a({"ManualMode":True,"EmergencyStop":False,"DownButton":True,"Start":True},
                   {"MoveDown":False,"MoveUp":False,"MoveLeft":False,"MoveRight":False,"ActivateGrip":False,"ActivateRelease":False})),
    c("P19-T2", a({"EmergencyStop":True,"DownLimitSwitch":True,"DownButton":True}, {"MoveDown":False})),
    c("P19-T3", a({"ManualMode":False,"SingleCycleMode":True,"Start":True,"DownLimitSwitch":False}),
      a({"Start":False,"DownLimitSwitch":True}), a({"DownLimitSwitch":False,"GripLimitSwitch":True}),
      a({"GripLimitSwitch":False,"UpLimitSwitch":True}), a({"UpLimitSwitch":False,"RightLimitSwitch":True}),
      a({"RightLimitSwitch":False,"DownLimitSwitch":True}), a({"DownLimitSwitch":False,"ReleaseLimitSwitch":True}),
      a({"ReleaseLimitSwitch":False,"UpLimitSwitch":True}), a({"UpLimitSwitch":False,"LeftLimitSwitch":True},
                                                                    {"MoveDown":False,"MoveUp":False,"MoveLeft":False,"MoveRight":False}))
]}
def p20_weigh(weight, expected):
    return [
        a({"Mode":False,"ForwardButton":False,"ReverseButton":False,"SensorFeed":False,
           "SensorWash":False,"SensorWeight":False,"SensorOutput":False,
           "washComplete":False,"weightComplete":False}),
        a({"Mode":True,"SensorFeed":True}),
        a({"SensorFeed":False,"SensorWash":True}),
        a({"washComplete":True}, {"MotorForward":True}),
        a({"SensorWash":False,"washComplete":False,"SensorWeight":True}),
        a({"weight":weight,"weightComplete":True}, expected),
    ]


V["P20"] = {"task_id":"P20", "cases":[
    c("P20-T1", a({"Mode":False,"SensorOutput":True,"SensorWash":True,
                    "ForwardButton":True,"ReverseButton":True}, {"MotorForward":False,"MotorReverse":False}),
      a({"ReverseButton":False}, {"MotorForward":True,"MotorReverse":False})),
    c("P20-T2", *p20_weigh(100.0, {"firingTemp":500.0}),
      *p20_weigh(150.0, {"firingTemp":525.0}), *p20_weigh(200.0, {"firingTemp":550.0})),
    c("P20-T3", *p20_weigh(99.0, {"kick":True}), *p20_weigh(201.0, {"kick":True}))
]}

V["S01"] = {"task_id":"S01", "cases":[
    c("S01-T1", a({"AutoEnable":False,"LevelHigh":False,"LevelLow":True}, {"Pump1Run":False,"Pump2Run":False,"NoAvailablePump":False})),
    c("S01-T2", a({"AutoEnable":True,"LevelHigh":True,"LevelLow":False,"Pump1Fault":False,"Pump2Fault":False},
                   {"Pump1Run":True,"Pump2Run":False})),
    c("S01-T3", a({"LevelHigh":False,"LevelLow":True,"CycleTime":"T#50ms"}, {"Pump1Run":True}, cycles=20),
      a({}, {"Pump1Run":False}, cycles=25)),
    c("S01-T4", a({"LevelLow":False,"LevelHigh":True}, {"Pump1Run":True}),
      a({"Pump1Fault":True}, {"Pump1Run":False,"Pump2Run":True})),
    c("S01-T5", a({"Pump2Fault":True}, {"Pump1Run":False,"Pump2Run":False,"NoAvailablePump":True}),
      a({"AutoEnable":False}, {"Pump1Run":False,"Pump2Run":False})),
    c("S01-T6", a({"AutoEnable":True,"Pump1Fault":False,"Pump2Fault":False,"LevelHigh":False,"LevelLow":True}),
      a({"LevelHigh":True,"LevelLow":False}, {"Pump2Run":True,"Pump1Run":False}))
]}
V["S02"] = {"task_id":"S02", "cases":[
    c("S02-T1", a({"EStopOK":True,"Start":True,"PartAtEntry":True,"PartAtExit":False,
                    "Stop":False,"CycleTime":"T#50ms"}, {"ConveyorForward":True,"ConveyorReverse":False})),
    c("S02-T2", a({"Jam":True}, {"ConveyorForward":False,"ConveyorReverse":True,"RetryCount":1}),
      a({"Jam":False}, {"ConveyorReverse":True}, cycles=18),
      a({}, {"ConveyorForward":True,"ConveyorReverse":False}, cycles=3)),
    c("S02-T3", a({"Jam":True}, {"ConveyorReverse":True,"RetryCount":2}),
      a({"Jam":False}, {"ConveyorForward":True}, cycles=21),
      a({"Jam":True}, {"FaultLatched":True,"RetryCount":2,"ConveyorForward":False,"ConveyorReverse":False})),
    c("S02-T4", a({"PartAtExit":True,"PartAtEntry":False,"Jam":False,"Start":False}),
      a({"PartAtExit":False,"Start":True,"PartAtEntry":True}, {"ConveyorForward":True}),
      a({"Jam":True}, {"ConveyorReverse":True}),
      a({"EStopOK":False}, {"ConveyorForward":False,"ConveyorReverse":False,"FaultLatched":True})),
    c("S02-T5", a({"EStopOK":True,"PartAtExit":True,"Jam":False,"Start":False}, {"RetryCount":0}),
      a({"PartAtExit":False,"Start":True}, {"FaultLatched":False}))
]}
V["S03"] = {"task_id":"S03", "cases":[
    c("S03-T1", a({"Level":25.0,"StartPermit":True,"HighHigh":False}, {"InletValve":True}),
      a({"Level":50.0}, {"InletValve":True})),
    c("S03-T2", a({"Level":70.0}, {"InletValve":False})),
    c("S03-T3", a({"HighHigh":True}, {"InletValve":False,"HighLevelAlarm":True}),
      a({"HighHigh":False,"Level":60.0,"ResetAlarm":True}, {"HighLevelAlarm":False})),
    c("S03-T4", a({"ResetAlarm":False,"StartPermit":False}, {"InletValve":False})),
    c("S03-T5", a({"StartPermit":True,"Level":-1.0}, {"InletValve":False,"HighLevelAlarm":False}),
      a({"Level":101.0}, {"InletValve":False,"HighLevelAlarm":False}))
]}
V["S04"] = {"task_id":"S04", "cases":[
    c("S04-T1", a({"EStopOK":True,"TargetA":10.0,"TargetB":20.0,"WeightA":0.0,"WeightB":0.0,"StartBatch":True}, {"ValveA":True}),
      a({"StartBatch":False,"WeightA":10.0}, {"ValveA":False,"ValveB":True}),
      a({"WeightB":20.0}, {"ValveB":False,"Mixer":True})),
    c("S04-T2", a({"StartBatch":False,"MixTime":"T#1s","CycleTime":"T#50ms","MixComplete":False}, {"Mixer":True,"OutletValve":False}, cycles=20)),
    c("S04-T3", a({"MixComplete":True,"DischargePermit":False}, {"OutletValve":False}),
      a({"DischargePermit":True}, {"OutletValve":True})),
    c("S04-T4", a({"EStopOK":False,"TargetA":0.0}, {"ValveA":False,"ValveB":False,"Mixer":False,"OutletValve":False,"BatchFault":True})),
    c("S04-T5", a({"Reset":True}, {"BatchFault":True}), a({"EStopOK":True,"Reset":False,"StartBatch":False}))
]}
V["S05"] = {"task_id":"S05", "cases":[
    c("S05-T1", a({"Enable":True,"Temperature":35.0,"Fan1Fault":False,"Fan2Fault":False,"CycleTime":"T#50ms"}, {"Fan1":True,"Fan2":False}),
      a({"Temperature":45.0}, {"Fan1":True,"Fan2":True})),
    c("S05-T2", a({"Temperature":43.0}, {"Fan1":True,"Fan2":True}),
      a({"Temperature":41.0}, {"Fan1":True,"Fan2":True}, cycles=200),
      a({}, {"Fan1":True,"Fan2":False})),
    c("S05-T3", a({"Temperature":45.0}, {"Fan2":False}), a({}, {"Fan2":True}, cycles=200)),
    c("S05-T4", a({"Temperature":200.0}, {"Fan1":False,"Fan2":False})),
    c("S05-T5", a({"Temperature":45.0,"Fan1Fault":True,"Fan2Fault":False}, {"Fan1":False,"Fan2":True}),
      a({"Fan2Fault":True}, {"Fan1":False,"Fan2":False,"CoolingAlarm":True}))
]}
V["S06"] = {"task_id":"S06", "cases":[
    c("S06-T1", a({"Demand":True,"PressureLow":True,"Compressor1Fault":False,"Compressor2Fault":False},
                   {"Compressor1Run":True,"Compressor2Run":False,"LeadIs1":True}),
      a({"PressureLow":False}, {"LeadIs1":False})),
    c("S06-T2", a({"PressureLow":True,"Demand":True,"Compressor1Fault":True}, {"Compressor1Run":False,"Compressor2Run":True})),
    c("S06-T3", a({"Compressor2Fault":True}, {"Compressor1Run":False,"Compressor2Run":False,"Fault":True})),
    c("S06-T4", a({"Reset":True,"Demand":True}, {"Fault":True}), a({"Reset":False,"Demand":False,"PressureLow":False}),
      a({"Reset":True,"Compressor1Fault":False,"Compressor2Fault":False}, {"Fault":False})),
    c("S06-T5", a({"Reset":False,"Demand":True,"PressureLow":True,"Compressor1Fault":False}, {"Compressor1Run":True}),
      a({"PressureLow":False}, {"Compressor1Run":False}))
]}
V["S07"] = {"task_id":"S07", "cases":[
    c("S07-T1", a({"GuardClosed":False,"EStopOK":False,"AutoPermit":False}, {"SafetyRelay":False,"TripLatched":True})),
    c("S07-T2", a({"GuardClosed":True,"EStopOK":True,"AutoPermit":False,"ResetButton":True}, {"TripLatched":False,"SafetyRelay":False})),
    c("S07-T3", a({"ResetButton":False,"AutoPermit":True}, {"SafetyRelay":True})),
    c("S07-T4", a({"GuardClosed":False}, {"SafetyRelay":False,"TripLatched":True})),
    c("S07-T5", a({"ResetButton":True,"GuardClosed":False}, {"TripLatched":True}),
      a({"GuardClosed":True,"EStopOK":False}, {"TripLatched":True}), a({"EStopOK":True,"AutoPermit":True}, {"TripLatched":True}))
]}
V["S08"] = {"task_id":"S08", "cases":[
    c("S08-T1", a({"PartPresent":True,"Defect":False,"ConveyorRunning":True,"CycleTime":"T#50ms","Reset":False}),
      a({"Defect":True}, {"RejectSolenoid":True,"RejectCount":1})),
    c("S08-T2", a({}, {"RejectCount":1}, cycles=2),
      a({}, {"RejectSolenoid":False,"RejectCount":1}, cycles=6)),
    c("S08-T3", a({"Defect":False,"PartPresent":False}, {"RejectCount":1}),
      a({"Defect":True}, {"RejectSolenoid":False,"RejectCount":1})),
    c("S08-T4", a({"Defect":False,"PartPresent":True,"ConveyorRunning":True}),
      a({"Defect":True}, {"RejectSolenoid":True,"RejectCount":2}),
      a({"Reset":True}, {"RejectCount":0,"RejectSolenoid":True}),
      a({"Reset":False}, {"RejectSolenoid":False}, cycles=6)),
    c("S08-T5", {"set":{"Defect":False}, "cycles":1, "seed":{"RejectCount":4294967295}},
      a({"Defect":True}, {"RejectCount":4294967295}))
]}
V["S09"] = {"task_id":"S09", "cases":[
    c("S09-T1", a({"SourceLevel":25.0,"DestinationLevel":50.0,"TransferEnable":True,"SourceLow":False,"DestinationHighHigh":False,"PumpFault":False}, {"TransferPump":True})),
    c("S09-T2", a({"SourceLevel":20.0}, {"TransferPump":False}), a({"SourceLevel":25.0,"DestinationLevel":80.0}, {"TransferPump":False})),
    c("S09-T3", a({"DestinationLevel":50.0,"DestinationHighHigh":True}, {"TransferPump":False,"DestinationHighAlarm":True}),
      a({"DestinationHighHigh":False,"SourceLow":True}, {"TransferPump":False,"SourceLowAlarm":True})),
    c("S09-T4", a({"SourceLow":False,"PumpFault":True}, {"TransferPump":False})),
    c("S09-T5", a({"PumpFault":False,"SourceLow":False,"DestinationHighHigh":False,"Reset":True},
                   {"SourceLowAlarm":False,"DestinationHighAlarm":False}))
]}
V["S10"] = {"task_id":"S10", "cases":[
    c("S10-T5", a({"Enable":False}, {"Heater":False,"SensorFault":True})),
    c("S10-T4", a({"SensorValid":True,"Temperature":20.0,"CycleTime":"T#50ms"}, {"SensorFault":True}, cycles=20),
      a({}, {"SensorFault":False}, cycles=20)),
    c("S10-T1", a({"Temperature":20.0,"Setpoint":22.0,"SensorValid":True,"Enable":True,"CycleTime":"T#50ms"}, {"Heater":True}),
      a({"Temperature":21.5}, {"Heater":True})),
    c("S10-T2", a({"Temperature":22.0}, {"Heater":False})),
    c("S10-T3", a({"SensorValid":False}, {"Heater":False,"SensorFault":True})),
]}


def main() -> None:
    dataset = json.loads((ROOT / "dataset/tasks.json").read_text(encoding="utf-8"))
    tasks = {task["id"]: task for task in dataset["tasks"]}
    OUT.mkdir(parents=True, exist_ok=True)
    for task_id, suite in V.items():
        source_cases = {case["id"]: case for case in tasks[task_id]["test_cases"]}
        for case in suite["cases"]:
            case["scenario"] = source_cases[case["id"]]["scenario"]
        path = OUT / f"{task_id}.json"
        path.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(V)} runtime vector suites ({sum(len(x['cases']) for x in V.values())} scenarios).")


if __name__ == "__main__":
    main()
