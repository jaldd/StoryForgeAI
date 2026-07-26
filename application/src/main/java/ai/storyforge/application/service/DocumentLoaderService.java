package ai.storyforge.application.service;

import ai.storyforge.application.config.ProjectProperties;
import ai.storyforge.application.service.markdown.MarkdownConversionStrategyFactory;
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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class DocumentLoaderService {

    private static final Logger log = LoggerFactory.getLogger(DocumentLoaderService.class);

    private final ProjectProperties projectProperties;
    private final DocumentRepository documentRepository;
    private final MarkdownConversionStrategyFactory markdownConversionStrategyFactory;

    private static final Pattern CHAPTER_PATTERN = Pattern.compile("^(第\\d+章|Chapter\\s+\\d+)[\\s_.-]*(.*)", Pattern.CASE_INSENSITIVE);
    private static final Pattern CHAPTER_NUMBER_PATTERN = Pattern.compile("(\\d+)");

    public DocumentLoaderService(ProjectProperties projectProperties, DocumentRepository documentRepository, MarkdownConversionStrategyFactory markdownConversionStrategyFactory) {
        this.projectProperties = projectProperties;
        this.documentRepository = documentRepository;
        this.markdownConversionStrategyFactory = markdownConversionStrategyFactory;
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

            // 转换非Markdown文件为Markdown，使用默认策略
//            content = markdownConversionStrategyFactory.getDefaultStrategy().convertToMarkdown(content, fileName);

            Document document = determineDocumentType(fileName, content, projectId);
            document.setFilePath(filePath.toString());
            
            // 计算相对目录路径
            Path basePath = Paths.get(projectProperties.getDocumentsPath()).toAbsolutePath().normalize();
            Path absoluteFilePath = filePath.toAbsolutePath().normalize();
            
            if (absoluteFilePath.startsWith(basePath)) {
                Path relativePath = basePath.relativize(absoluteFilePath);
                Path parentDir = relativePath.getParent();
                if (parentDir != null) {
                    document.setDirectoryPath(parentDir.toString());
                } else {
                    document.setDirectoryPath("");
                }
            }
            
            documentRepository.save(document);

            log.info("Loaded document: {} (type: {}, dir: {})", fileName, document.getType(), document.getDirectoryPath());
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
        
        // 首先获取现有文档，按文件路径分组
        Map<String, Document> existingDocsByPath = new HashMap<>();
        documentRepository.findByProjectId(projectId)
            .stream()
            .filter(doc -> doc.getFilePath() != null)
            .forEach(doc -> existingDocsByPath.put(doc.getFilePath(), doc));
        
        // 加载新文档
        Map<String, Document> newDocsByPath = new HashMap<>();
        String docsPath = projectProperties.getDocumentsPath();
        Path path = Paths.get(docsPath);
        
        if (Files.exists(path) && Files.isDirectory(path)) {
            try {
                Files.walk(path)
                    .filter(Files::isRegularFile)
                    .filter(this::isSupportedFile)
                    .forEach(filePath -> {
                        try {
                            String content = Files.readString(filePath);
                            // 转换非Markdown文件为Markdown，使用默认策略
                            content = markdownConversionStrategyFactory.getDefaultStrategy().convertToMarkdown(content, filePath.getFileName().toString());
                            Document doc = determineDocumentType(filePath.getFileName().toString(), content, projectId);
                            doc.setFilePath(filePath.toString());
                            
                            // 计算相对目录路径
                            Path basePath = Paths.get(projectProperties.getDocumentsPath()).toAbsolutePath().normalize();
                            Path absoluteFilePath = filePath.toAbsolutePath().normalize();
                            
                            if (absoluteFilePath.startsWith(basePath)) {
                                Path relativePath = basePath.relativize(absoluteFilePath);
                                Path parentDir = relativePath.getParent();
                                if (parentDir != null) {
                                    doc.setDirectoryPath(parentDir.toString());
                                } else {
                                    doc.setDirectoryPath("");
                                }
                            }
                            
                            newDocsByPath.put(filePath.toString(), doc);
                        } catch (IOException e) {
                            log.error("Failed to load document: {}", filePath, e);
                        }
                    });
            } catch (IOException e) {
                log.error("Error walking documents directory", e);
            }
        }
        
        // 处理文档更新
        for (Map.Entry<String, Document> entry : newDocsByPath.entrySet()) {
            String filePath = entry.getKey();
            Document newDoc = entry.getValue();
            
            if (existingDocsByPath.containsKey(filePath)) {
                // 文档已存在，检查是否需要更新
                Document existingDoc = existingDocsByPath.get(filePath);
                if (!newDoc.getContent().equals(existingDoc.getContent())) {
                    // 内容变化，更新现有文档
                    existingDoc.updateContent(newDoc.getContent());
                    documentRepository.save(existingDoc);
                    log.info("Updated document: {}", filePath);
                }
                // 从现有文档映射中移除，剩下的就是需要删除的
                existingDocsByPath.remove(filePath);
            } else {
                // 新文档，直接保存
                documentRepository.save(newDoc);
                log.info("Added new document: {}", filePath);
            }
        }
        
        // 删除不再存在的文档
        for (Document docToDelete : existingDocsByPath.values()) {
            documentRepository.delete(docToDelete.getDocumentId());
            log.info("Deleted document: {}", docToDelete.getFilePath());
        }
    }
}
