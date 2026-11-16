"""Home page: Cloud FinOps platform overview."""

import streamlit as st

from finops import ui

ui.page_setup("Home", ":material/home:")
st.title("Intelligent Cloud FinOps Platform")
st.caption("Floci (local AWS emulator) + Python/boto3 + Streamlit")
