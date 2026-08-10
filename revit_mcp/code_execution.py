# -*- coding: UTF-8 -*-
"""
Code Execution Module for Revit MCP
Handles direct execution of IronPython code in Revit context.
"""
from pyrevit import routes, revit, DB
from .utils import safe_tx, suppress_warnings, model_elements, safe_name, family_name
import json
import logging
import sys
import traceback
from StringIO import StringIO

# Standard logger setup
logger = logging.getLogger(__name__)


def register_code_execution_routes(api):
    """Register code execution routes with the API."""

    @api.route("/execute_code/", methods=["POST"])
    def execute_code(doc, uidoc, request):
        """
        Execute IronPython code in Revit context.

        Expected payload:
        {
            "code": "python code as string",
            "description": "optional description of what the code does",
            "use_transaction": true   # set false for UI ops like switching the active view
        }
        """
        try:
            # Parse the request data
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            )
            code_to_execute = data.get("code", "")
            description = data.get("description", "Code execution")

            if not code_to_execute:
                return routes.make_response(
                    data={"error": "No code provided"}, status=400
                )

            logger.info("Executing code: {}".format(description))

            old_stdout = sys.stdout
            captured_output = StringIO()
            sys.stdout = captured_output

            namespace = {
                "doc": doc,
                "uidoc": uidoc,
                "DB": DB,
                "revit": revit,
                # Transaction/collector helpers. safe_tx is the only correct way
                # to open a transaction here: a bare DB.Transaction lets a routine
                # Revit warning go modal, which blocks the UI thread so the
                # external event never completes and every later request times out
                # until a human clicks the dialog.
                "safe_tx": safe_tx,
                "suppress_warnings": suppress_warnings,
                "model_elements": model_elements,
                # Name accessors. Element.Name is shadowed under IronPython and
                # throws AttributeError on FamilySymbol and friends; these are
                # bound here so the trap cannot be walked into. Both return None
                # rather than a placeholder, so a miss fails visibly.
                "safe_name": safe_name,
                "family_name": family_name,
                "__builtins__": __builtins__,
                "print": lambda *args: captured_output.write(
                    " ".join(str(arg) for arg in args) + "\n"
                ),
            }

            try:
                exec(code_to_execute, namespace)

                sys.stdout = old_stdout
                output = captured_output.getvalue()
                captured_output.close()

                return routes.make_response(
                    data={
                        "status": "success",
                        "description": description,
                        "output": (
                            output
                            if output
                            else "Code executed successfully (no output)"
                        ),
                        # The submitted script is deliberately NOT echoed back.
                        # The caller already has it in context; returning it
                        # roughly doubles the cost of every call for no
                        # information gain.
                    }
                )

            except Exception as exec_error:
                sys.stdout = old_stdout
                partial_output = captured_output.getvalue()
                captured_output.close()

                error_traceback = traceback.format_exc()
                error_type = type(exec_error).__name__
                error_msg = str(exec_error)
                enhanced_message = "{}: {}".format(error_type, error_msg)

                hints = []
                if error_type == "AttributeError":
                    if "Name" in error_msg:
                        hints.append(
                            "Element.Name is shadowed under IronPython. Use the "
                            "injected safe_name(el) / family_name(el) helpers. Do NOT "
                            "use getattr(el, 'Name', 'N/A') - the placeholder makes "
                            "every name comparison silently miss, so the job reports "
                            "'0 found' instead of failing."
                        )
                    else:
                        hints.append(
                            "Some Revit API properties are not directly accessible in "
                            "IronPython. Prefer an explicit try/except that re-raises or "
                            "returns None over a getattr default, which hides the miss."
                        )
                elif error_type == "NullReferenceException" or "NoneType" in error_msg:
                    hints.append(
                        "An object is None/null. Check if elements exist before "
                        "accessing their properties: 'if element:'"
                    )
                elif error_type == "InvalidOperationException":
                    hints.append(
                        "This operation may require a transaction. Use the injected "
                        "helper: t = safe_tx(doc, 'desc'); ...; t.Commit(). Never a "
                        "bare DB.Transaction - it lets a routine Revit warning go "
                        "modal and hang the bridge until a human clicks the dialog."
                    )

                logger.error("Code execution failed: {}".format(enhanced_message))

                # code_attempted is deliberately omitted. Measured: errors
                # averaged 3,954 B against 885 B for a success, and the echoed
                # script was 96% of that - so 10% of calls produced 32% of all
                # bytes returned. The caller already has the script in context;
                # the traceback's line number is the only new information.
                response_data = {
                    "status": "error",
                    "error": enhanced_message,
                    "error_type": error_type,
                    "traceback": error_traceback,
                }

                if partial_output:
                    response_data["partial_output"] = partial_output

                if hints:
                    response_data["hints"] = hints

                return routes.make_response(data=response_data, status=500)

        except Exception as e:
            logger.error("Execute code request failed: {}".format(str(e)))
            return routes.make_response(data={"error": str(e)}, status=500)

    logger.info("Code execution routes registered successfully.")
