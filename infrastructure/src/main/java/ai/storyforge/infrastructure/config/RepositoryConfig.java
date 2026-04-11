package ai.storyforge.infrastructure.config;

import ai.storyforge.domain.repository.DocumentRepository;
import ai.storyforge.infrastructure.persistence.InMemoryDocumentRepository;
import ai.storyforge.infrastructure.persistence.JpaDocumentRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

@Configuration
public class RepositoryConfig {

    @Bean
    @Primary
    @ConditionalOnProperty(name = "storyforge.repository.type", havingValue = "in-memory", matchIfMissing = true)
    public DocumentRepository inMemoryDocumentRepository() {
        return new InMemoryDocumentRepository();
    }

    @Bean
    @ConditionalOnProperty(name = "storyforge.repository.type", havingValue = "jpa")
    public DocumentRepository jpaDocumentRepository(JpaDocumentRepository jpaDocumentRepository) {
        return jpaDocumentRepository;
    }
}
