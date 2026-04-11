package ai.storyforge.application.dto;

public record ChatRequest(
    String message,
    String projectId
) {}
