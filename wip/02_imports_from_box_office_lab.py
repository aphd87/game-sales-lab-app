import hashlib
import html
import hmac
import inspect
import json
import math
import os
import threading
from collections import OrderedDict
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


# --- Classroom load: skip Altair's schema check ----------------------------------------------------------------
# Altair re-validates every chart against the full Vega-Lite JSON schema each time it is drawn, for every student,
# which was the biggest single CPU cost in a 65-student load test. These charts are fixed code, already validated
# while building the app, so draw them without the check. Guarded so reruns don't stack wrappers.
def _skip_altair_validation():
    for cls in (alt.Chart, alt.TopLevelMixin):
        if "to_dict" in cls.__dict__ and not getattr(cls.to_dict, "_no_validate", False):
            orig = cls.to_dict

            def to_dict(self, validate=False, *args, _orig=orig, **kw):
                return _orig(self, validate, *args, **kw)
            to_dict._no_validate = True
            cls.to_dict = to_dict


_skip_altair_validation()
