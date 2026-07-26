package ai.storyforge.application.service;

import ai.storyforge.application.config.ProjectProperties;
import ai.storyforge.application.dto.DocumentDto;
import ai.storyforge.application.dto.OptimizationResultDto;
import ai.storyforge.application.dto.ProjectDto;
import ai.storyforge.application.port.inbound.ProjectUseCase;
import ai.storyforge.application.port.outbound.ModelGateway;
import ai.storyforge.application.service.markdown.MarkdownConversionStrategyFactory;
import ai.storyforge.domain.exception.DocumentNotFoundException;
import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.NovelProject;
import ai.storyforge.domain.model.vo.DocumentId;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.DocumentRepository;
import ai.storyforge.domain.repository.NovelProjectRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;

@Service
@Transactional
public class ProjectService implements ProjectUseCase {

    private static final Logger log = LoggerFactory.getLogger(ProjectService.class);

    private final ProjectProperties projectProperties;
    private final NovelProjectRepository novelProjectRepository;
    private final DocumentRepository documentRepository;
    private final DocumentLoaderService documentLoaderService;
    private final MarkdownConversionStrategyFactory markdownConversionStrategyFactory;
    private final ModelGateway modelGateway;

    public ProjectService(
            ProjectProperties projectProperties,
            NovelProjectRepository novelProjectRepository,
            DocumentRepository documentRepository,
            DocumentLoaderService documentLoaderService,
            MarkdownConversionStrategyFactory markdownConversionStrategyFactory,
            ModelGateway modelGateway) {
        this.projectProperties = projectProperties;
        this.novelProjectRepository = novelProjectRepository;
        this.documentRepository = documentRepository;
        this.documentLoaderService = documentLoaderService;
        this.markdownConversionStrategyFactory = markdownConversionStrategyFactory;
        this.modelGateway = modelGateway;
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
            .orElseThrow(() -> new DocumentNotFoundException(documentId));
    }

    @Override
    public DocumentDto getChapter(int chapterNumber) {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        return documentRepository.findChapterByNumber(projectId, chapterNumber)
            .map(this::toDocumentDto)
            .orElseThrow(() -> new DocumentNotFoundException("Chapter " + chapterNumber));
    }

    @Override
    public void reloadDocuments() {
        documentLoaderService.reloadDocuments();
    }

    @Override
    public OptimizationResultDto optimizeDocument(String documentId) {
        Document document = documentRepository.findById(DocumentId.of(documentId))
            .orElseThrow(() -> new DocumentNotFoundException(documentId));

        String originalContent = document.getContent();
        
        // 1. 检查内容并提供建议
        String suggestions = checkDocumentContent(originalContent);
        
        // 2. 转换为标准Markdown格式
        String optimizedContent = markdownConversionStrategyFactory.getDefaultStrategy()
            .convertToMarkdown(originalContent, document.getName());
        
        // 3. 检查是否有变化
        boolean hasChanges = !originalContent.equals(optimizedContent);
        
        log.info("Optimization preview for document: {} (changes: {})", documentId, hasChanges);
        
        return new OptimizationResultDto(
            documentId,
            originalContent,
            optimizedContent,
            suggestions,
            hasChanges
        );
    }

    @Override
    public void applyOptimization(String documentId, String optimizedContent) {
        Document document = documentRepository.findById(DocumentId.of(documentId))
            .orElseThrow(() -> new DocumentNotFoundException(documentId));

        document.updateContent(optimizedContent);
        documentRepository.save(document);
        
        log.info("Applied optimization for document: {}", documentId);
    }

    private String checkDocumentContent(String content) {
        try {
            String prompt = "请检查以下小说内容，找出其中的错别字、语法错误和不合理之处，并提供改进建议：\n\n" + content;
            return modelGateway.generateContent(prompt);
        } catch (Exception e) {
            log.error("Error checking document content", e);
            return "内容检查失败，请稍后重试。";
        }
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
            doc.getDirectoryPath(),
            doc.getCreatedAt(),
            doc.getUpdatedAt()
        );
    }
}
