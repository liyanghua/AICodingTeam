from __future__ import annotations

from pathlib import Path
import typer
from rich import print

from .parser import DocumentParser
from .compiler import SkillCompiler
from .evals import CompileEvaluator

app = typer.Typer(help="Compile business strategy documents into executable Agent skills.")


@app.command()
def compile(
    input: Path = typer.Option(..., "--input", "-i", help="Input business document path."),
    output: Path = typer.Option(..., "--output", "-o", help="Output skill package directory."),
) -> None:
    parser = DocumentParser()
    ir = parser.parse(input)
    metrics = CompileEvaluator().evaluate(ir)
    out = SkillCompiler().compile(ir, output)
    print(f"[green]Compiled skill package:[/green] {out}")
    print({"strategy_id": ir.strategy_id, "workflow_steps": len(ir.workflow_steps), "outputs": len(ir.outputs), "data_requirements": len(ir.data_requirements), "eval": metrics})


@app.command()
def inspect(input: Path = typer.Option(..., "--input", "-i")) -> None:
    ir = DocumentParser().parse(input)
    print(ir.model_dump(mode="json"))


if __name__ == "__main__":
    app()
