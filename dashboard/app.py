from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from dashboard.ui.sidebar import render_left_panel


st.set_page_config(
    page_title="Hybrid Renewable Energy Simulation & Optimization Platform",
    page_icon="⚡",
    layout="wide",
)


def image_to_base64(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode()


def render_home_page() -> None:
    logo_path = "dashboard/assets/insolare_logo.png"
    logo_b64 = image_to_base64(logo_path)

    st.markdown(
        """
        <style>
        .hero-wrap {
            background: linear-gradient(180deg, #f7f8fa 0%, #f3f5f8 100%);
            border: 1px solid #e6eaf0;
            border-radius: 24px;
            padding: 36px 36px 28px 36px;
            margin-bottom: 28px;
        }

        .hero-grid {
            display: block;
            width: 100%;
        }

        .hero-title {
            font-size: 58px;
            line-height: 1.12;
            font-weight: 800;
            color: #123c7b;
            margin: 14px 0 24px 0;
            width: 100%;
            max-width: none;
        }

        .hero-subtitle {
            font-size: 20px;
            color: #42546b;
            margin-bottom: 30px;
            width: 100%;
            max-width: 100%;
            line-height: 1.7;
        }

        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 10px;
        }

        .pill {
            background: #eef3f8;
            border: 1px solid #d3dce8;
            color: #163b73;
            border-radius: 999px;
            padding: 10px 16px;
            font-size: 15px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }


        .hero-logo {
            margin-bottom: 8px;
        }

        .section-wrap {
            background: #ffffff;
            border: 1px solid #e6eaf0;
            border-radius: 22px;
            padding: 28px 28px 18px 28px;
            margin-bottom: 22px;
        }

        .section-title {
            color: #123c7b;
            font-size: 26px;
            font-weight: 750;
            margin-bottom: 10px;
        }

        .section-text {
            color: #4e6077;
            font-size: 16px;
            line-height: 1.7;
        }

        .workflow-grid {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 14px;
            margin-top: 18px;
        }

        .workflow-step {
            background: #f8fafc;
            border: 1px solid #e4e9f0;
            border-radius: 18px;
            padding: 16px 14px;
            min-height: 120px;
        }

        .workflow-step h5 {
            margin: 0 0 10px 0;
            color: #123c7b;
            font-size: 17px;
            font-weight: 700;
        }

        .workflow-step p {
            margin: 0;
            color: #53657b;
            font-size: 14px;
            line-height: 1.55;
        }

        .start-box {
            background: #eef6ff;
            border: 1px solid #cfe0f5;
            color: #163b73;
            border-radius: 18px;
            padding: 18px 20px;
            font-size: 16px;
            font-weight: 600;
        }

        @media (max-width: 1200px) {
            .hero-grid {
                grid-template-columns: 1fr;
            }

            .workflow-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    left_html = f"""
    <div>
        {"<img class='hero-logo' src='data:image/png;base64," + logo_b64 + "' width='280' />" if logo_b64 else "<h2 style='color:#123c7b;'>InSolare Energy Ltd.</h2>"}
        <div class="hero-title">
            Hybrid Renewable Energy Simulation & Optimization Platform
        </div>
        <div class="hero-subtitle">
            Design, simulate, and evaluate hybrid renewable energy systems including Solar PV, Wind Turbines, Battery Energy Storage Systems (BESS), Converters, and Grid integration for project-level planning and analysis.
        </div>
        <div class="pill-row">
            <div class="pill">✅ Solar + Wind + BESS + Grid</div>
            <div class="pill">✅ Project-Based Workflow</div>
            <div class="pill">✅ Optimization-Ready Architecture</div>
        </div>
    </div>
    """


    st.markdown(
        f"""
        <div class="hero-wrap">
            <div class="hero-grid">
                {left_html}
                
        """,
        unsafe_allow_html=True,
    )

    

    st.markdown(
        """
        <div class="section-wrap">
            <div class="section-title">Platform Scope</div>
            <div class="section-text">
                This platform is being developed to support hybrid renewable energy project planning with a modular,
                simulation-ready architecture. It is intended to evolve toward detailed hourly dispatch simulation,
                system sizing, and techno-economic evaluation of Solar + Wind + BESS + Grid configurations.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="start-box">
            Use the left sidebar to begin with the <b>Design</b> page and set up your first hybrid renewable energy project.
        </div>
        """,
        unsafe_allow_html=True,
    )


render_left_panel()
render_home_page()