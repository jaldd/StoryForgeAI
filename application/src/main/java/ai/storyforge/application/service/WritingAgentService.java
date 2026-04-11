package ai.storyforge.application.service;

import ai.storyforge.application.config.ProjectProperties;
import ai.storyforge.application.port.inbound.WritingAgentUseCase;
import ai.storyforge.application.port.outbound.ModelGateway;
import ai.storyforge.domain.model.Document;
import ai.storyforge.domain.model.DocumentType;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.DocumentRepository;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.List;
import java.util.stream.Collectors;

@Service
public class WritingAgentService implements WritingAgentUseCase {

    private final ModelGateway modelGateway;
    private final DocumentRepository documentRepository;
    private final ProjectProperties projectProperties;

    public WritingAgentService(
            ModelGateway modelGateway,
            DocumentRepository documentRepository,
            ProjectProperties projectProperties) {
        this.modelGateway = modelGateway;
        this.documentRepository = documentRepository;
        this.projectProperties = projectProperties;
    }

    @Override
    public String chat(String message, String projectId) {
        String context = buildContext();
        String fullPrompt = buildFullPrompt(message, context);
        return modelGateway.chat(fullPrompt);
    }

    @Override
    public Flux<String> chatStream(String message, String projectId) {
        String context = buildContext();
        String fullPrompt = buildFullPrompt(message, context);
        return modelGateway.chatStream(fullPrompt);
    }

    private String buildContext() {
        NovelProjectId projectId = NovelProjectId.of(projectProperties.getDefaultProjectId());
        StringBuilder context = new StringBuilder();

        List<Document> chapters = documentRepository.findByProjectIdAndType(projectId, DocumentType.CHAPTER);
        if (!chapters.isEmpty()) {
            context.append("【小说章节】\n");
            chapters.stream()
                .sorted((a, b) -> {
                    Integer numA = a.getChapterNumber();
                    Integer numB = b.getChapterNumber();
                    if (numA == null) return 1;
                    if (numB == null) return -1;
                    return numA.compareTo(numB);
                })
                .forEach(chapter -> {
                    context.append("第").append(chapter.getChapterNumber()).append("章: ")
                           .append(chapter.getTitle() != null ? chapter.getTitle() : chapter.getName())
                           .append("\n");
                    if (chapter.getContent() != null) {
                        String preview = chapter.getContent().length() > 500
                            ? chapter.getContent().substring(0, 500) + "..."
                            : chapter.getContent();
                        context.append(preview).append("\n\n");
                    }
                });
        }

        List<Document> characters = documentRepository.findByProjectIdAndType(projectId, DocumentType.CHARACTER);
        if (!characters.isEmpty()) {
            context.append("【角色设定】\n");
            characters.forEach(character -> {
                context.append(character.getName()).append(":\n");
                if (character.getContent() != null) {
                    String preview = character.getContent().length() > 300
                        ? character.getContent().substring(0, 300) + "..."
                        : character.getContent();
                    context.append(preview).append("\n\n");
                }
            });
        }

        List<Document> worlds = documentRepository.findByProjectIdAndType(projectId, DocumentType.WORLD);
        if (!worlds.isEmpty()) {
            context.append("【世界观设定】\n");
            worlds.forEach(world -> {
                context.append(world.getName()).append(":\n");
                if (world.getContent() != null) {
                    String preview = world.getContent().length() > 300
                        ? world.getContent().substring(0, 300) + "..."
                        : world.getContent();
                    context.append(preview).append("\n\n");
                }
            });
        }

        return context.toString();
    }

    private String buildFullPrompt(String userMessage, String context) {
        if (context.isBlank()) {
            return userMessage;
        }

        return """
            你是一个专业的小说创作助手。以下是当前小说项目的相关信息：

            %s

            用户的需求是：%s

            请根据上述信息，帮助用户完成创作任务。
            """.formatted(context, userMessage);
    }
}
