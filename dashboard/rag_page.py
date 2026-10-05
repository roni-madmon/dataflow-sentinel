"""Question answering over the indexed project documentation."""

import streamlit as st

from dashboard.client import ApiError, call_api


def validate_answer(result):
    answerable = result.get("answerable")
    statements = result.get("statements")

    if type(answerable) is not bool or not isinstance(statements, list):
        raise ApiError("The RAG response has an unexpected format.")
    if len(statements) > 2 or answerable != bool(statements):
        raise ApiError("The RAG response is inconsistent.")

    for field in ("request_id", "generation_model"):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise ApiError("The RAG response is missing its model or request ID.")

    for statement in statements:
        if not isinstance(statement, dict):
            raise ApiError("The RAG response contains an invalid statement.")
        for field in ("text", "source_id", "quote", "source", "section"):
            value = statement.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ApiError("The RAG response is missing an answer or citation.")


def show_rag_page(api_url):
    st.title("Knowledge assistant")
    st.write("Ask about HGB V2, its evaluation results, and documented limitations.")
    st.caption(
        "Current knowledge base: the HGB V2 model card. "
        "Individual job logs are not included."
    )

    with st.expander("Example questions"):
        st.code(
            "What is the alert threshold for HGB V2?\n"
            "What was the precision on the Test set?\n"
            "Does a score of 0.97 mean a 97 percent probability of failure?",
            language=None,
            wrap_lines=True,
        )

    with st.form("rag_question_form"):
        question = st.text_area(
            "Your question",
            value="What is the alert threshold for HGB V2?",
            max_chars=1000,
            height=110,
            key="rag_question",
        )
        submitted = st.form_submit_button("Ask", type="primary")

    api_url = api_url.strip().rstrip("/")

    if submitted:
        st.session_state.pop("rag_last_result", None)
        question = question.strip()
        if not question:
            st.warning("Enter a question.")
            return

        try:
            with st.spinner("Searching documents and generating an answer..."):
                result = call_api(
                    api_url,
                    "/rag/ask",
                    {"question": question},
                    timeout=400,
                )
                validate_answer(result)
        except ApiError as error:
            st.error(str(error))
            return

        st.session_state["rag_last_result"] = {
            "api_url": api_url,
            "question": question,
            "response": result,
        }

    saved = st.session_state.get("rag_last_result")
    if not saved or saved["api_url"] != api_url:
        return

    result = saved["response"]
    st.divider()
    st.subheader("Last submitted question")
    st.text(saved["question"])
    st.caption("Submit again to get an answer to an edited question.")

    if not result["answerable"]:
        st.info("Insufficient information in the retrieved sources.")
    else:
        st.subheader("Answer")
        for number, statement in enumerate(result["statements"], start=1):
            st.text(statement["text"])
            with st.expander(f"Source {number}: {statement['section']}", expanded=True):
                st.text(f"{statement['source_id']} | {statement['source']}")
                st.code(statement["quote"], language=None, wrap_lines=True)

    with st.expander("Response details"):
        st.json(result)
