import streamlit as st


def apply_global_style():
    st.markdown(
        """
        <style>
          .block-container { padding-top: 0.8rem; padding-bottom: 1rem; }
          [data-testid="stSidebar"] { width: 320px !important; }
          .homer-title { font-size: 18px; font-weight: 700; }
          .homer-sub { font-size: 12px; opacity: 0.8; }

          .topbar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom: 10px; }
          .topbtn { border:1px solid #ddd; border-radius:8px; padding:6px 10px; background:#f7f7f7; }
          .topbtn-active { border:1px solid #1f77b4; background:#e8f2ff; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def top_bar(active: str):
    items = ["Design", "Load", "Resources", "Components", "Project", "Results", "Optimization"]
    st.markdown('<div class="topbar">', unsafe_allow_html=True)
    cols = st.columns(len(items))
    for i, name in enumerate(items):
        with cols[i]:
            if name == active:
                st.markdown(f'<div class="topbtn topbtn-active">✅ {name}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="topbtn">{name}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)