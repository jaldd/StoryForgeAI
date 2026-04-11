package ai.storyforge.application.port.inbound;

import ai.storyforge.application.dto.DocumentDto;
import ai.storyforge.application.dto.ProjectDto;
import java.util.List;

public interface ProjectUseCase {
    ProjectDto getDefaultProject();
    List<DocumentDto> getAllDocuments();
    List<DocumentDto> getAllChapters();
    DocumentDto getDocument(String documentId);
    DocumentDto getChapter(int chapterNumber);
    void reloadDocuments();
}
