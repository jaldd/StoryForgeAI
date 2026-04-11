package ai.storyforge.application.service;

import ai.storyforge.application.config.ProjectProperties;
import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.DocumentType;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.DocumentRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.nio.file.*;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class DocumentLoaderService {

    private static final Logger log = LoggerFactory.getLogger(DocumentLoaderService.class);

    private final ProjectProperties projectProperties;
    private final DocumentRepository documentRepository;

    private static final Pattern CHAPTER_PATTERN = Pattern.compile("^(第\\d+章|Chapter\\s+\\d+)[\\s_.-]*(.*)", Pattern.CASE_INSENSITIVE);
    private static final Pattern CHAPTER_NUMBER_PATTERN = Pattern.compile("(\\d+)");

    public DocumentLoaderService(ProjectProperties projectProperties, DocumentRepository documentRepository) {
        this.projectProperties = projectProperties;
        this.documentRepository = documentRepository;
    }

    @PostConstruct
    public void init() {
        loadDocumentsFromDirectory();
    }

    public void loadDocumentsFromDirectory() {
        String docsPath = projectProperties.getDocumentsPath();
        Path path = Paths.get(docsPath);

        if (!Files.exists(path)) {
            log.info("Documents directory does not exist: {}, creating it", docsPath);
            try {
                Files.createDirectories(path);
            } catch (IOException e) {
                log.error("Failed to create documents directory", e);
            }
            return;
        }

        if (!Files.isDirectory(path)) {
            log.warn("Documents path is not a directory: {}", docsPath);
            return;
        }

        log.info("Loading documents from: {}", docsPath);

        try {
            Files.walk(path)
                .filter(Files::isRegularFile)
                .filter(this::isSupportedFile)
                .forEach(this::loadDocument);
        } catch (IOException e) {
            log.error("Error walking documents directory", e);
        }
    }

    private boolean isSupportedFile(Path path) {
        String fileName = path.getFileName().toString().toLowerCase();
        return fileName.endsWith(".md") || 
               fileName.endsWith(".txt") ||
               fileName.endsWith(".html") ||
               fileName.endsWith(".json");
    }

    private void loadDocument(Path filePath) {
        try {
            String fileName = filePath.getFileName().toString();
            String content = Files.readString(filePath);
            NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());

            Document document = determineDocumentType(fileName, content, projectId);
            document.setFilePath(filePath.toString());
            documentRepository.save(document);

            log.info("Loaded document: {} (type: {})", fileName, document.getType());
        } catch (IOException e) {
            log.error("Failed to load document: {}", filePath, e);
        }
    }

    private Document determineDocumentType(String fileName, String content, NovelProjectId projectId) {
        String lowerFileName = fileName.toLowerCase();

        if (lowerFileName.contains("character") || lowerFileName.contains("角色")) {
            String name = extractNameFromFileName(fileName);
            return Document.createCharacter(projectId, name, content);
        }

        if (lowerFileName.contains("world") || lowerFileName.contains("世界观") || 
            lowerFileName.contains("setting") || lowerFileName.contains("设定")) {
            String name = extractNameFromFileName(fileName);
            return Document.createWorld(projectId, name, content);
        }

        Matcher chapterMatcher = CHAPTER_PATTERN.matcher(fileName);
        if (chapterMatcher.find()) {
            String chapterTitle = chapterMatcher.group(2);
            if (chapterTitle == null || chapterTitle.isBlank()) {
                chapterTitle = fileName;
            }

            int chapterNumber = extractChapterNumber(fileName);
            Document chapter = Document.createChapter(projectId, chapterNumber, chapterTitle.trim(), content);
            return chapter;
        }

        if (lowerFileName.contains("outline") || lowerFileName.contains("大纲") || 
            lowerFileName.contains("plot") || lowerFileName.contains("情节")) {
            String name = extractNameFromFileName(fileName);
            return new Document(
                ai.storyforge.domain.model.vo.DocumentId.generate(),
                projectId,
                DocumentType.OUTLINE,
                name,
                content
            );
        }

        String name = extractNameFromFileName(fileName);
        return new Document(
            ai.storyforge.domain.model.vo.DocumentId.generate(),
            projectId,
            DocumentType.NOTE,
            name,
            content
        );
    }

    private String extractNameFromFileName(String fileName) {
        String name = fileName;
        int lastDot = fileName.lastIndexOf('.');
        if (lastDot > 0) {
            name = fileName.substring(0, lastDot);
        }
        return name;
    }

    private int extractChapterNumber(String fileName) {
        Matcher matcher = CHAPTER_NUMBER_PATTERN.matcher(fileName);
        if (matcher.find()) {
            try {
                return Integer.parseInt(matcher.group(1));
            } catch (NumberFormatException e) {
                return 1;
            }
        }
        return 1;
    }

    public List<Document> getAllDocuments() {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        return documentRepository.findByProjectId(projectId);
    }

    public List<Document> getAllChapters() {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        return documentRepository.findAllChapters(projectId);
    }

    public void reloadDocuments() {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        documentRepository.findByProjectId(projectId)
            .forEach(doc -> documentRepository.delete(doc.getDocumentId()));
        loadDocumentsFromDirectory();
    }
}
