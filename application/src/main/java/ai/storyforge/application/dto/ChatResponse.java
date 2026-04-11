package ai.storyforge.application.dto;

public record ChatResponse(
    String content,
    String traceId,
    int tokenCount,
    double estimatedCost
) {}
