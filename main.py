import os
from datetime import datetime
import uuid

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.prompt import Prompt
from rich.table import Table
from pyfiglet import Figlet

from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

from deepresearch.graph import graph
from deepresearch.jev_integration import JevConfigurationError, validate_jev_configuration

console = Console()

def render_banner(title: str = "DeepDoc.ai", subtitle: str = ""):
    figlet = Figlet(font="banner3-d", width=200)
    ascii_art = figlet.renderText(title)

    panel = Panel.fit(
        f"[bold bright_magenta]{ascii_art}[/bold bright_magenta]\n[green]{subtitle}[/green]",
        border_style="cyan",
        padding=(1, 2),
        title="[bold yellow]WELCOME[/bold yellow]",
    )

    console.print(panel)

def run_tool(topic, outline, resource_path, config):
    validate_jev_configuration()
    for event in graph.stream(
        {"topic": topic, "outline": outline, "resource_path": resource_path},
        config=config,
    ):
        if "resource_setup" in event:
            console.print(Panel("Setting up the database for you...", title="RESOURCE SETUP", style="yellow", width=120))
        
        elif "report_structure_planner" in event:
            msg = event["report_structure_planner"]["messages"][-1].content
            console.print(Panel(Text(msg, style="white"), title="REPORT STRUCTURE PLANNER", style="green", width=120))
        
        elif "section_formatter" in event:
            data = event["section_formatter"]

            table = Table(title="Section Formatter", show_header=True, header_style="bold cyan")
            table.add_column("Section", style="bold yellow")
            table.add_column("Sub-sections", style="green")

            for section in data["sections"]:
                subs = "\n- " + "\n- ".join(section.sub_sections)
                table.add_row(section.section_name, subs)

            console.print(Panel(table, style="cyan", width=120))
        
        elif "research_agent" in event:
            console.print(Panel("Research agent is extracting and processing the required details.", 
                                title="RESEARCH AGENT", style="magenta", width=120))
        
        elif "final_report_writer" in event:
            report = event["final_report_writer"]["final_report_content"]
            console.print(Panel(Markdown(report), title="FINAL REPORT", style="bold blue", width=200))
            os.makedirs("output_folder", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            md_filename = f"output_folder/final_report_{timestamp}.md"

            with open(md_filename, "w", encoding="utf-8") as f:
                f.write(report)

            console.print(f"[green]Report exported to[/green] [cyan]{md_filename}[/cyan]")
        
        else:
            msg = event["human_feedback"]["messages"][-1].content
            console.print(Panel(Text(msg, style="italic white"), title="HUMAN FEEDBACK", style="red", width=120))


if __name__ == "__main__":
    from configuration import THREAD_CONFIG
    
    render_banner("DeepDoc.ai", "AI-powered Local Deep Research")

    try:
        validate_jev_configuration()
    except JevConfigurationError as exc:
        console.print(Panel(str(exc), title="JEV CONFIGURATION", style="bold red", width=120))
        raise SystemExit(1)

    topic = Prompt.ask("[bold yellow]Enter your topic[/bold yellow]").strip()
    outline = Prompt.ask("[bold yellow]Enter your outline or goal[/bold yellow]").strip()
    resource_path = Prompt.ask("[bold yellow]Enter the directory path[/bold yellow]").strip()

    run_tool(topic, outline, resource_path, THREAD_CONFIG)
