from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    assemble_node,
    plan_node,
    research_node,
    review_node,
    write_node,
)
from app.graph.state import PipelineState


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("plan", plan_node)
    graph.add_node("research", research_node)
    graph.add_node("write", write_node)
    graph.add_node("review", review_node)
    graph.add_node("assemble", assemble_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "write")
    graph.add_edge("write", "review")
    graph.add_edge("review", "assemble")
    graph.add_edge("assemble", END)

    return graph.compile()
