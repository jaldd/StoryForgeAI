package ai.storyforge.application.service;

import ai.storyforge.application.config.ProjectProperties;
import ai.storyforge.application.dto.DocumentDto;
import ai.storyforge.application.dto.ProjectDto;
import ai.storyforge.application.port.inbound.ProjectUseCase;
import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.NovelProject;
import ai.storyforge.domain.model.vo.DocumentId;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.DocumentRepository;
import ai.storyforge.domain.repository.NovelProjectRepository;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;

@Service
public class ProjectService implements ProjectUseCase {

    private final ProjectProperties projectProperties;
    private final NovelProjectRepository novelProjectRepository;
    private final DocumentRepository documentRepository;
    private final DocumentLoaderService documentLoaderService;

    public ProjectService(
            ProjectProperties projectProperties,
            NovelProjectRepository novelProjectRepository,
            DocumentRepository documentRepository,
            DocumentLoaderService documentLoaderService) {
        this.projectProperties = projectProperties;
        this.novelProjectRepository = novelProjectRepository;
        this.documentRepository = documentRepository;
        this.documentLoaderService = documentLoaderService;
        ensureDefaultProjectExists();
    }

    private void ensureDefaultProjectExists() {
        NovelProjectId defaultProjectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        Optional<NovelProject> existingProject = novelProjectRepository.findById(defaultProjectId);

        if (existingProject.isEmpty()) {
            NovelProject project = new NovelProject(
                defaultProjectId,
                projectProperties.getDefaultTitle(),
                projectProperties.getDefaultAuthor()
            );
            novelProjectRepository.save(project);
        }
    }

    @Override
    public ProjectDto getDefaultProject() {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        NovelProject project = novelProjectRepository.findById(projectId)
            .orElseThrow(() -> new RuntimeException("Default project not found"));

        List<Document> documents = documentRepository.findByProjectId(projectId);

        return new ProjectDto(
            project.getProjectId().toStringValue(),
            project.getTitle(),
            project.getAuthor(),
            project.getCreatedAt(),
            project.getUpdatedAt(),
            documents.size()
        );
    }

    @Override
    public List<DocumentDto> getAllDocuments() {
        return documentLoaderService.getAllDocuments().stream()
            .map(this::toDocumentDto)
            .collect(Collectors.toList());
    }

    @Override
    public List<DocumentDto> getAllChapters() {
        return documentLoaderService.getAllChapters().stream()
            .map(this::toDocumentDto)
            .collect(Collectors.toList());
    }

    @Override
    public DocumentDto getDocument(String documentId) {
        return documentRepository.findById(DocumentId.of(documentId))
            .map(this::toDocumentDto)
            .orElse(null);
    }

    @Override
    public DocumentDto getChapter(int chapterNumber) {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        return documentRepository.findChapterByNumber(projectId, chapterNumber)
            .map(this::toDocumentDto)
            .orElse(null);
    }

    @Override
    public void reloadDocuments() {
        documentLoaderService.reloadDocuments();
    }

    private DocumentDto toDocumentDto(Document doc) {
        return new DocumentDto(
            doc.getDocumentId().value(),
            doc.getType(),
            doc.getName(),
            doc.getTitle(),
            doc.getChapterNumber(),
            doc.getContent(),
            doc.getWordCount(),
            doc.getFilePath(),
            doc.getCreatedAt(),
            doc.getUpdatedAt()
        );
    }
}
