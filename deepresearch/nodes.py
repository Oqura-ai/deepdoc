from typing import Literal

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate, ChatPromptTemplate, MessagesPlaceholder

from langgraph.types import Command, Send

from deepresearch.prompts import *
from deepresearch.client_init import init_llm
from deepresearch.chunk_prep import create_chunks
from deepresearch.jev_integration import (
    build_reflection_feedback,
    evaluate_passages,
    evaluate_subsection_coverage,
    format_evidence,
    missing_subsections,
    select_evidence,
)
from deepresearch.qdrant_setup import rag_pipeline_setup, retrieve_from_store
from deepresearch.schema import (
    AgentState,
    ResearchState,
    Sections,
    Queries,
    RetrievedPassage,
    SearchResult,
)

from configuration import LLM_CONFIG

llm = init_llm(
    provider=LLM_CONFIG["provider"],
    model=LLM_CONFIG["model"],
    temperature=LLM_CONFIG["temperature"],
    max_retries=LLM_CONFIG.get("max_retries", 6),
    timeout=LLM_CONFIG.get("timeout", 120.0),
)

def resource_setup_node(state: AgentState, config: RunnableConfig):
    thread_id = config.get("configurable").get("thread_id")
    directory_path = state.get("resource_path")
    chunks = create_chunks(directory_path)
    rag_pipeline_setup(thread_id, chunks)


def report_structure_planner_node(state: AgentState, config: RunnableConfig):
    report_structure_planner_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(REPORT_STRUCTURE_PLANNER_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(
            template="""
            Topic: {topic}
            Outline: {outline}
            """
        ),
        MessagesPlaceholder(variable_name="messages")
    ])

    report_structure_planner_llm = report_structure_planner_system_prompt | llm
    result = report_structure_planner_llm.invoke(state)
    return {"messages": [result]}


def human_feedback_node(state: AgentState, config: RunnableConfig)->Command[Literal["section_formatter", "report_structure_planner"]]:
    human_message = input("Please provide feedback on the report structure (type 'continue' to continue): ")
    report_structure = state.get("messages")[-1].content
    if human_message == "continue":
        return Command(
            goto="section_formatter",
            update={"messages": [HumanMessage(content=human_message)], "report_structure": report_structure}
        )
    else:
        return Command(
            goto="report_structure_planner",
            update={"messages": [HumanMessage(content=human_message)]}
        )



def section_formatter_node(state: AgentState, config: RunnableConfig) -> Command[Literal["research_agent"]]:
    section_formatter_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(SECTION_FORMATTER_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(template="{report_structure}"),
    ])

    section_formatter_llm = section_formatter_system_prompt | llm.with_structured_output(
        Sections,
        method="function_calling",
    )
    result = section_formatter_llm.invoke(state)
    return Command(
        update={"sections": result.sections},
        goto=[
            Send(
                "research_agent",
                {
                    "section": s,
                }
            ) for s in result.sections
        ]
    )


def section_knowledge_node(state: ResearchState, config: RunnableConfig):
    section_knowledge_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(SECTION_KNOWLEDGE_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(template="{section}"),
    ])

    section_knowledge_llm = section_knowledge_system_prompt | llm
    result = section_knowledge_llm.invoke(state)
    return {"knowledge": result.content}


def query_generator_node(state: ResearchState, config: RunnableConfig):
    query_generator_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(QUERY_GENERATOR_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(template="Section: {section}\nPrevious Queries: {searched_queries}\nReflection Feedback: {reflection_feedback}"),
    ])

    query_generator_llm = query_generator_system_prompt | llm.with_structured_output(
        Queries,
        method="function_calling",
    )
    configurable = config.get("configurable") or {}

    input_data = {
        **state,
        "reflection_feedback": state.get("reflection_feedback", ""),
        "searched_queries": state.get("searched_queries", []),
        **configurable  # includes max_queries, search_depth, etc.
    }

    result = query_generator_llm.invoke(input_data, config)
    queries = result.queries[: configurable.get("max_queries", 3)]
    return {"generated_queries": queries, "searched_queries": queries}


def rag_search_node(state: ResearchState, config: RunnableConfig):
    queries = state["generated_queries"]
    configurable = config.get("configurable") or {}
    retrieved_passages = []
    for query in queries:
        response = retrieve_from_store(
            query.query,
            configurable.get("thread_id"),
            configurable.get("n_points", 6),
        )
        for result in response:
            document = result.payload["document"]
            retrieved_passages.append(
                RetrievedPassage(
                    point_id=str(result.id),
                    query=query,
                    filename=document["filename"],
                    page_number=document["page_number"],
                    chunk_id=document.get("chunk_id", str(result.id)),
                    page_content=document["page_content"],
                    qdrant_score=getattr(result, "score", None),
                )
            )
    return {"retrieved_passages": retrieved_passages}


def evidence_gate_node(state: ResearchState, config: RunnableConfig):
    configurable = config.get("configurable") or {}
    decisions = evaluate_passages(state.get("retrieved_passages", []), configurable)
    selected = select_evidence(
        decisions,
        keep_per_query=configurable.get("evidence_keep_per_query", 3),
    )

    by_query = {}
    for decision in selected:
        by_query.setdefault(decision.passage.query.query, []).append(format_evidence(decision))

    search_results = [
        SearchResult(query=query, raw_content=by_query.get(query.query, []))
        for query in state["generated_queries"]
    ]
    return {
        "search_results": search_results,
        "evidence_decisions": decisions,
    }


def result_accumulator_node(state: ResearchState, config: RunnableConfig):
    result_accumulator_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(RESULT_ACCUMULATOR_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(template="{search_results}"),
    ])

    result_accumulator_llm = result_accumulator_system_prompt | llm
    result = result_accumulator_llm.invoke(state)
    return {"accumulated_content": result.content}


def reflection_feedback_node(state: ResearchState, config: RunnableConfig) -> Command[Literal["final_section_formatter", "query_generator"]]:
    reflection_count = state.get("reflection_count", 0)
    configurable = config.get("configurable") or {}
    coverage = evaluate_subsection_coverage(
        state["section"],
        state.get("accumulated_content", ""),
    )
    missing = missing_subsections(
        state["section"],
        coverage,
        threshold=configurable.get("jev_reflection_threshold", 0.70),
    )
    feedback = build_reflection_feedback(missing)

    if not missing or reflection_count >= configurable.get("num_reflections", 2):
        return Command(
            update={
                "reflection_feedback": feedback,
                "reflection_scores": coverage,
            },
            goto="final_section_formatter"
        )

    return Command(
        update={
            "reflection_feedback": feedback,
            "reflection_scores": coverage,
            "reflection_count": reflection_count + 1,
        },
        goto="query_generator"
    )
    

def final_section_formatter_node(state: ResearchState, config: RunnableConfig):
    final_section_formatter_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(FINAL_SECTION_FORMATTER_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(
            template=(
                "Internal Knowledge: {knowledge}\n"
                "Accepted Local-Document Evidence: {search_results}\n"
                "Curated Evidence: {accumulated_content}"
            )
        ),
    ])

    final_section_formatter_llm = final_section_formatter_system_prompt | llm
    result = final_section_formatter_llm.invoke(state, config)
    return {"final_section_content": [result.content]}


def final_report_writer_node(state: AgentState, config: RunnableConfig):
    final_report_writer_system_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(FINAL_REPORT_WRITER_SYSTEM_PROMPT_TEMPLATE),
        HumanMessagePromptTemplate.from_template(template="Report Structure: {report_structure}\nSection Contents: {final_section_content}"),
    ])

    final_report_writer_llm = final_report_writer_system_prompt | llm
    result = final_report_writer_llm.invoke(state)
    return {"final_report_content": result.content}
