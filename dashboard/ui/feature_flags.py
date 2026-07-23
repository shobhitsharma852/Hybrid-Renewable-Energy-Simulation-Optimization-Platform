"""
Central on/off switches for optional dashboard UI.

Flip a flag to True to bring a hidden feature back into the UI without
touching or restoring any surrounding code — the implementation underneath
stays exactly as it is either way.
"""

# Per-component "Sizing Mode" radio (Discrete Options vs InSolare Optimizer) on
# the PV / Wind / Battery / Converter panels, plus the "Optimizer mode" radio
# and "Run InSolare Optimizer" button on the Optimization page.
# core/optimization/insolare_optimizer.py stays fully implemented regardless
# of this flag — only its dashboard entry points are gated.
SHOW_INSOLARE_OPTIMIZER_UI = False
