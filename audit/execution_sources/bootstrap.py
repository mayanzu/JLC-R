from pathlib import Path
import importlib.util,sys
HERE=Path(__file__).resolve().parent;PROJECT=HERE.parents[2]
RGP=HERE.parent/'jlcr2_demand_guard_20261025_221513'
sys.path.insert(0,str(PROJECT/'code/simulation'));sys.path.insert(0,str(RGP))
from trigger_controls import Candidate as RGPController
from validation_model import StreamingBank
path=HERE.parent/'efr_common_executor_20261026_233900/src/development_inputs.py'
spec=importlib.util.spec_from_file_location('cadence_inputs',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
make_input=module.make_input
