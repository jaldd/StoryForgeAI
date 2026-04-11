package ai.storyforge.infrastructure.persistence;

import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.DocumentType;
import ai.storyforge.domain.model.vo.DocumentId;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.DocumentRepository;
import org.springframework.stereotype.Repository;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

//@Repository
public class InMemoryDocumentRepository implements DocumentRepository {

    private final Map<DocumentId, Document> documents = new ConcurrentHashMap<>();

    @Override
    public Document save(Document document) {
        documents.put(document.getDocumentId(), document);
        return document;
    }

    @Override
    public Optional<Document> findById(DocumentId documentId) {
        return Optional.ofNullable(documents.get(documentId));
    }

    @Override
    public List<Document> findByProjectId(NovelProjectId projectId) {
        return documents.values().stream()
            .filter(d -> d.getProjectId().equals(projectId))
            .sorted(Comparator.comparing(Document::getCreatedAt).reversed())
            .collect(Collectors.toList());
    }

    @Override
    public List<Document> findByProjectIdAndType(NovelProjectId projectId, DocumentType type) {
        return documents.values().stream()
            .filter(d -> d.getProjectId().equals(projectId))
            .filter(d -> d.getType() == type)
            .sorted(Comparator.comparing(Document::getCreatedAt).reversed())
            .collect(Collectors.toList());
    }

    @Override
    public List<Document> findAllChapters(NovelProjectId projectId) {
        return documents.values().stream()
            .filter(d -> d.getProjectId().equals(projectId))
            .filter(d -> d.getType() == DocumentType.CHAPTER)
            .sorted(Comparator.comparing(Document::getChapterNumber, Comparator.nullsLast(Comparator.naturalOrder())))
            .collect(Collectors.toList());
    }

    @Override
    public Optional<Document> findChapterByNumber(NovelProjectId projectId, int chapterNumber) {
        return documents.values().stream()
            .filter(d -> d.getProjectId().equals(projectId))
            .filter(d -> d.getType() == DocumentType.CHAPTER)
            .filter(d -> d.getChapterNumber() != null && d.getChapterNumber() == chapterNumber)
            .findFirst();
    }

    @Override
    public void delete(DocumentId documentId) {
        documents.remove(documentId);
    }

    public void clear() {
        documents.clear();
    }
}
