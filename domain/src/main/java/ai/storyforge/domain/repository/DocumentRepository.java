package ai.storyforge.domain.repository;

import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.DocumentType;
import ai.storyforge.domain.model.vo.DocumentId;
import ai.storyforge.domain.model.vo.NovelProjectId;
import java.util.List;
import java.util.Optional;

public interface DocumentRepository {
    Document save(Document document);
    Optional<Document> findById(DocumentId documentId);
    List<Document> findByProjectId(NovelProjectId projectId);
    List<Document> findByProjectIdAndType(NovelProjectId projectId, DocumentType type);
    List<Document> findAllChapters(NovelProjectId projectId);
    Optional<Document> findChapterByNumber(NovelProjectId projectId, int chapterNumber);
    void delete(DocumentId documentId);
}
