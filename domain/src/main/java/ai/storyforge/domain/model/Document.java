package ai.storyforge.domain.model;

import ai.storyforge.domain.model.vo.DocumentId;
import ai.storyforge.domain.model.vo.NovelProjectId;
import jakarta.persistence.Embedded;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import java.time.LocalDateTime;

@Entity
public class Document {

    @EmbeddedId
    private DocumentId documentId;

    @Embedded
    private NovelProjectId projectId;

    @Enumerated(EnumType.STRING)
    private DocumentType type;

    private String name;

    private String title;

    private Integer chapterNumber;

    private String content;

    private Integer wordCount;

    private String filePath;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    protected Document() {}

    public Document(DocumentId documentId, NovelProjectId projectId, DocumentType type, String name, String content) {
        this.documentId = documentId;
        this.projectId = projectId;
        this.type = type;
        this.name = name;
        this.content = content;
        this.createdAt = LocalDateTime.now();
        this.updatedAt = LocalDateTime.now();
        this.wordCount = content != null ? content.length() / 2 : 0;
    }

    public static Document createChapter(NovelProjectId projectId, int chapterNumber, String title, String content) {
        Document doc = new Document(
            DocumentId.generate(),
            projectId,
            DocumentType.CHAPTER,
            title,
            content
        );
        doc.chapterNumber = chapterNumber;
        doc.title = title;
        return doc;
    }

    public static Document createCharacter(NovelProjectId projectId, String name, String content) {
        return new Document(
            DocumentId.generate(),
            projectId,
            DocumentType.CHARACTER,
            name,
            content
        );
    }

    public static Document createWorld(NovelProjectId projectId, String name, String content) {
        return new Document(
            DocumentId.generate(),
            projectId,
            DocumentType.WORLD,
            name,
            content
        );
    }

    public DocumentId getDocumentId() { return documentId; }
    public NovelProjectId getProjectId() { return projectId; }
    public DocumentType getType() { return type; }
    public String getName() { return name; }
    public String getTitle() { return title; }
    public Integer getChapterNumber() { return chapterNumber; }
    public String getContent() { return content; }
    public Integer getWordCount() { return wordCount; }
    public String getFilePath() { return filePath; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }

    public void setFilePath(String filePath) {
        this.filePath = filePath;
        this.updatedAt = LocalDateTime.now();
    }

    public void updateContent(String content) {
        this.content = content;
        this.wordCount = content != null ? content.length() / 2 : 0;
        this.updatedAt = LocalDateTime.now();
    }
}
