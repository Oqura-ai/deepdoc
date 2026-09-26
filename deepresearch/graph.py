from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from deepresearch.nodes import (
    evidence_gate_node,
    final_report_writer_node,
    final_section_formatter_node,
    human_feedback_node,
    query_generator_node,
    rag_search_node,
    reflection_feedback_node,
    report_structure_planner_node,
    resource_setup_node,
    result_accumulator_node,
    section_formatter_node,
    section_knowledge_node,
)
from deepresearch.schema import AgentState, ResearchState, SectionOutput

research_builder = StateGraph(ResearchState, output=SectionOutput)

research_builder.add_node("section_knowledge", section_knowledge_node)
research_builder.add_node("query_generator", query_generator_node)
research_builder.add_node("rag_search", rag_search_node)
research_builder.add_node("evidence_gate", evidence_gate_node)
research_builder.add_node("result_accumulator", result_accumulator_node)
research_builder.add_node("reflection", reflection_feedback_node)
research_builder.add_node("final_section_formatter", final_section_formatter_node)

research_builder.add_edge(START, "section_knowledge")
research_builder.add_edge("section_knowledge", "query_generator")
research_builder.add_edge("query_generator", "rag_search")
research_builder.add_edge("rag_search", "evidence_gate")
research_builder.add_edge("evidence_gate", "result_accumulator")
research_builder.add_edge("result_accumulator", "reflection")
research_builder.add_edge("final_section_formatter", END)

memory_saver = MemorySaver()

builder = StateGraph(AgentState)

builder.add_node("resource_setup", resource_setup_node)
builder.add_node("report_structure_planner", report_structure_planner_node)
builder.add_node("human_feedback", human_feedback_node)
builder.add_node("section_formatter", section_formatter_node)
builder.add_node("research_agent", research_builder.compile())
builder.add_node("final_report_writer", final_report_writer_node)

builder.set_entry_point("resource_setup")
builder.add_edge("resource_setup", "report_structure_planner")
builder.add_edge("report_structure_planner", "human_feedback")
builder.add_edge("research_agent", "final_report_writer")
builder.add_edge("final_report_writer", END)

graph = builder.compile(checkpointer=memory_saver)
