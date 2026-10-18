#!/bin/bash
# usage: a.sh NAME  -> snap + full DOM text into audit2/NAME.{png,txt}
source ~/android-ref-lab/env.sh
D=~/android-ref-lab/audit2; n=$1
adb exec-out screencap -p > $D/$n.png
~/android-ref-lab/texts.sh > $D/$n.txt
cat $D/$n.txt | head -${2:-60}
