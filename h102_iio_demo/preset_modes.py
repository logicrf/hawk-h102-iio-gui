"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       preset_modes.py
@brief      Group actual independent/shared-LO preset IDs while retaining 29 logical combinations.
@details    Interpret the approved -common suffix without inventing unavailable device IDs.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
"""


def profile_mode(profile_id):
    """Identify LO topology from actual IDs; legacy unsuffixed presets remain independent."""
    return 'shared-lo2' if profile_id.endswith('-common') else 'independent'


def logical_profile(profile_id):
    """Display a rate/bandwidth label while keeping full IDs for device operations."""
    return profile_id.removesuffix('-common')


def mode_profiles(available, mode):
    """Return only available presets in this mode and preserve server ordering."""
    return [(logical_profile(name),name) for name in available if profile_mode(name)==mode]


# End of file: preset_modes.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
