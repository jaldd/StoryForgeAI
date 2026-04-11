package ai.storyforge.application.dto;

import ai.storyforge.domain.model.DocumentType;
import java.time.LocalDateTime;

public record DocumentDto(
    String documentId,
    DocumentType type,
    String name,
    String title,
    Integer chapterNumber,
    String content,
    Integer wordCount,
    String filePath,
    LocalDateTime createdAt,
    LocalDateTime updatedAt
) {}
