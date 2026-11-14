PROGRAM P14
VAR_INPUT
    ipText : STRING(254);
END_VAR
VAR_OUTPUT
    ipValue : UDINT;
END_VAR
VAR
    textLength : INT;
    position : INT;
    characterByte : BYTE;
    octetValue : UDINT;
    assembledValue : UDINT;
    octetCount : INT;
    segmentHasDigit : BOOL;
    validIPv4 : BOOL;
    allOctetsInRange0to255 : BOOL;
END_VAR

(* Reinitialize parsing state on every scan. *)
ipValue := UDINT#0;
textLength := LEN(ipText);
octetValue := UDINT#0;
assembledValue := UDINT#0;
octetCount := 0;
segmentHasDigit := FALSE;
validIPv4 := textLength > 0;
allOctetsInRange0to255 := TRUE;

FOR position := 0 TO textLength - 1 DO
    (* CODESYS STRING indexing returns a byte; index 1 is the first character. *)
    characterByte := ipText[position];

    IF (characterByte >= BYTE#48) AND (characterByte <= BYTE#57) THEN
        segmentHasDigit := TRUE;
        octetValue := octetValue * UDINT#10
                      + BYTE_TO_UDINT(characterByte) - UDINT#48;

        (* Check immediately, preventing overflow even for long segments. *)
        IF octetValue > UDINT#255 THEN
            allOctetsInRange0to255 := FALSE;
            validIPv4 := FALSE;
            EXIT;
        END_IF;

    ELSIF characterByte = BYTE#46 THEN
        (* Only three separators, each following a nonempty segment. *)
        IF (NOT segmentHasDigit) OR (octetCount >= 3) THEN
            validIPv4 := FALSE;
            EXIT;
        END_IF;

        assembledValue := SHL(assembledValue, 8) OR octetValue;
        octetCount := octetCount + 1;
        octetValue := UDINT#0;
        segmentHasDigit := FALSE;

    ELSE
        (* Reject whitespace, signs, and every other nondigit character. *)
        validIPv4 := FALSE;
        EXIT;
    END_IF;
END_FOR;

IF validIPv4 THEN
    IF segmentHasDigit AND (octetCount = 3) THEN
        assembledValue := SHL(assembledValue, 8) OR octetValue;
        octetCount := octetCount + 1;
    ELSE
        validIPv4 := FALSE;
    END_IF;
END_IF;

IF validIPv4 AND allOctetsInRange0to255 AND (octetCount = 4) THEN
    ipValue := assembledValue;
END_IF;
END_PROGRAM