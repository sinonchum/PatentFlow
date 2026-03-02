

@app.post("/api/generate-chart", response_model=GenerateChartResponse)
def generate_chart(req: GenerateChartRequest) -> GenerateChartResponse:
    """
    Generate a claim chart comparing claim features against prior art.
    
    Uses deterministic heuristic parsing for claim splitting and prior art matching.
    """
    try:
        generator = ClaimChartGenerator()
        result = generator.execute(
            claim_text=req.claim_text,
            prior_art_text=req.prior_art_text,
            office_action_text=req.office_action_text
        )
        
        return GenerateChartResponse(
            status=result.status,
            chart=result.data.get("chart", []),
            cited_docs=result.data.get("cited_docs", []),
            warnings=result.warnings
        )
    except Exception as e:
        return GenerateChartResponse(
            status="error",
            chart=[],
            cited_docs=[],
            error=f"CLAIM_CHART_GENERATION_ERROR: {str(e)}",
            warnings=["Failed to generate claim chart"]
        )


@app.post("/api/verify-translation", response_model=VerifyTranslationResponse)
def verify_translation(req: VerifyTranslationRequest) -> VerifyTranslationResponse:
    """
    Verify translation against glossary rules for Art. 123(2) compliance.
    
    Uses deterministic dictionary-based risk detection.
    """
    try:
        verifier = TranslationVerifier()
        result = verifier.execute(
            original_cn=req.original_cn,
            target_en=req.target_en,
            back_cn=req.back_cn
        )
        
        return VerifyTranslationResponse(
            status=result.status,
            rows=result.data.get("rows", []),
            markdown_table=result.data.get("markdown_table", ""),
            overall_risk=result.data.get("overall_risk", "Safe"),
            warnings=result.warnings
        )
    except Exception as e:
        return VerifyTranslationResponse(
            status="error",
            rows=[],
            markdown_table="",
            overall_risk="Unknown",
            error=f"TRANSLATION_VERIFICATION_ERROR: {str(e)}",
            warnings=["Failed to verify translation"]
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for all unhandled exceptions."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": f"INTERNAL_SERVER_ERROR: {str(exc)}",
            "detail": "An unexpected error occurred. Please try again or contact support."
        }
    )
