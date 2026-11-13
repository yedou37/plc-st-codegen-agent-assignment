# CODESYS support data types

Import these files into CODESYS as DUTs before compiling solutions that use the
corresponding task-defined record type:

- `ST_Pump.st` is used by task P07. `priority` and `selection` are read-only to
  the control logic; `RunComd` is written each scan.
- `ST_AnalogChannel.st` is used by task P08 for channel settings and results.
- `ST_Recipe.st` is used by task P17. A zero `recipeID` marks an empty slot.

These definitions follow the interfaces in `dataset/tasks.json`. They are
project support objects; the original generated ST files remain unchanged.
