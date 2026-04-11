package ai.storyforge.application.dto;

import java.time.LocalDateTime;

public record ProjectDto(
    String projectId,
    String title,
    String author,
    LocalDateTime createdAt,
    LocalDateTime updatedAt,
    int documentCount
) {}
