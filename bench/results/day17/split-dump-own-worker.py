import faulthandler
from pathlib import Path
with (Path.home()/".caravan/day17/split-followup/n2-python-stacks.txt").open("w") as f:faulthandler.dump_traceback(file=f,all_threads=True)
