package ai.storyforge.infrastructure.persistence;

import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.DocumentType;
import ai.storyforge.domain.model.vo.DocumentId;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.DocumentRepository;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import jakarta.persistence.TypedQuery;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

//@Repository
@Transactional
public class JpaDocumentRepository implements DocumentRepository {

    @PersistenceContext
    private EntityManager entityManager;

    @Override
    public Document save(Document document) {
        if (entityManager.find(Document.class, document.getDocumentId()) == null) {
            entityManager.persist(document);
            return document;
        } else {
            return entityManager.merge(document);
        }
    }

    @Override
    public Optional<Document> findById(DocumentId documentId) {
        return Optional.ofNullable(entityManager.find(Document.class, documentId));
    }

    @Override
    public List<Document> findByProjectId(NovelProjectId projectId) {
        TypedQuery<Document> query = entityManager.createQuery(
            "SELECT d FROM Document d WHERE d.projectId = :projectId ORDER BY d.createdAt DESC",
            Document.class
        );
        query.setParameter("projectId", projectId);
        return query.getResultList();
    }

    @Override
    public List<Document> findByProjectIdAndType(NovelProjectId projectId, DocumentType type) {
        TypedQuery<Document> query = entityManager.createQuery(
            "SELECT d FROM Document d WHERE d.projectId = :projectId AND d.type = :type ORDER BY d.createdAt DESC",
            Document.class
        );
        query.setParameter("projectId", projectId);
        query.setParameter("type", type);
        return query.getResultList();
    }

    @Override
    public List<Document> findAllChapters(NovelProjectId projectId) {
        TypedQuery<Document> query = entityManager.createQuery(
            "SELECT d FROM Document d WHERE d.projectId = :projectId AND d.type = 'CHAPTER' ORDER BY d.chapterNumber ASC",
            Document.class
        );
        query.setParameter("projectId", projectId);
        return query.getResultList();
    }

    @Override
    public Optional<Document> findChapterByNumber(NovelProjectId projectId, int chapterNumber) {
        TypedQuery<Document> query = entityManager.createQuery(
            "SELECT d FROM Document d WHERE d.projectId = :projectId AND d.type = 'CHAPTER' AND d.chapterNumber = :chapterNumber",
            Document.class
        );
        query.setParameter("projectId", projectId);
        query.setParameter("chapterNumber", chapterNumber);
        List<Document> results = query.getResultList();
        return results.isEmpty() ? Optional.empty() : Optional.of(results.get(0));
    }

    @Override
    public void delete(DocumentId documentId) {
        Document document = entityManager.find(Document.class, documentId);
        if (document != null) {
            entityManager.remove(document);
        }
    }
}
